"""把同一数据库中的四个 SQLite Registry 组合成统一入口。"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Self

from forgemind.schema.tasks import (
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_observation_registry import (
    SQLiteObservationRegistry,
)
from forgemind.state.sqlite_permission_decision_registry import (
    SQLitePermissionDecisionRegistry,
)
from forgemind.state.sqlite_permission_request_registry import (
    SQLitePermissionRequestRegistry,
)
from forgemind.state.sqlite_task_registry import (
    DuplicateTaskIdError,
    SQLiteTaskRegistry,
)
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
    InvalidInitialTaskStatusError,
    SQLiteTaskStatusRegistry,
)


class TaskStatusTaskMismatchError(ValueError):
    """初始状态没有引用即将创建的同一个任务。"""

    def __init__(self, task_id: str, status_task_id: str) -> None:
        self.task_id = task_id
        self.status_task_id = status_task_id
        super().__init__(
            f"任务与初始状态不匹配：{task_id} != {status_task_id}"
        )


@dataclass(frozen=True, slots=True)
class SQLiteForgeMindState:
    """持有一组连接到同一数据库且依赖关系正确的 Registry。"""

    database_path: Path
    tasks: SQLiteTaskRegistry
    task_statuses: SQLiteTaskStatusRegistry
    actions: SQLiteActionRegistry
    permission_requests: SQLitePermissionRequestRegistry
    permission_decisions: SQLitePermissionDecisionRegistry
    observations: SQLiteObservationRegistry

    def get_task_view(self, task_id: str) -> TaskStateView:
        """组合不可变任务来源、当前状态和有序 Action 历史。"""

        return TaskStateView(
            task=self.tasks.get(task_id),
            current_status=self.task_statuses.get_current(task_id),
            # 第一步：调用 self.actions.list_for_task(task_id)，把返回的
            # 有序元组传给 actions。不要直接查询 SQLite，也不要按
            # action_id 再次排序。
            actions=self.actions.list_for_task(task_id),
        )

    def create_task(
        self,
        task: TaskRecord,
        initial_status: TaskStatusRecord,
    ) -> None:
        """在一个事务中同时创建任务及 revision=1 的 RUNNING 状态。"""

        if initial_status.task_id != task.task_id:
            raise TaskStatusTaskMismatchError(
                task.task_id,
                initial_status.task_id,
            )
        if (
            initial_status.revision != 1
            or initial_status.status is not TaskStatus.RUNNING
        ):
            raise InvalidInitialTaskStatusError(task.task_id)

        task_payload_json = task.model_dump_json()
        status_payload_json = initial_status.model_dump_json()

        try:
            # 第一步：用 self.database_path 打开一个连接，在 with 事务中
            # 启用 foreign_keys，并执行 BEGIN IMMEDIATE。
            with sqlite3.connect(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                # 第二步：用参数化 INSERT 写入 tasks 的
                # task_id、project_root、task_payload_json。
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id,
                        project_root,
                        payload_json
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.project_root,
                        task_payload_json,
                    ),
                )

                # 第三步：仍使用同一个 connection，用参数化 INSERT 写入
                # task_statuses 的五个字段。不要调用两个 Registry 的公开
                # 方法，因为它们会各自打开连接，无法组成同一个事务。
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id,
                        task_id,
                        revision,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        initial_status.task_status_id,
                        initial_status.task_id,
                        initial_status.revision,
                        initial_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_task_creation_conflict(task, initial_status)

    def _raise_task_creation_conflict(
        self,
        task: TaskRecord,
        initial_status: TaskStatusRecord,
    ) -> None:
        """在事务回滚后，把 SQLite 冲突映射为稳定领域错误。"""

        with sqlite3.connect(self.database_path) as connection:
            task_exists = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (initial_status.task_status_id,),
            ).fetchone()

        if task_exists is not None:
            raise DuplicateTaskIdError(task.task_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                initial_status.task_status_id
            ) from None

        raise RuntimeError("任务创建违反未知的 SQLite 完整性约束")

    @classmethod
    def open(cls, database_path: Path) -> Self:
        """打开数据库，并按依赖顺序建立完整的 State 入口。"""

        # 第一步：调用 resolve()，把数据库路径统一成绝对路径。
        resolved_database_path = database_path.resolve()
        # 第二步：先创建 Task Registry，再创建 Action Registry；后续会让
        # 每个 Action 的 task_id 引用已经持久化的任务。
        tasks = SQLiteTaskRegistry(resolved_database_path)
        task_statuses = SQLiteTaskStatusRegistry(resolved_database_path)
        actions = SQLiteActionRegistry(resolved_database_path)
        # 第三步：创建 PermissionRequest Registry，并传入 Action Registry。
        permission_requests = SQLitePermissionRequestRegistry(
            resolved_database_path,
            actions,
        )
        # 第四步：创建 PermissionDecision Registry，传入请求 Registry；
        # 同时创建 Observation Registry，传入 Action Registry。
        permission_decisions = SQLitePermissionDecisionRegistry(
            resolved_database_path,
            permission_requests,
        )
        observations = SQLiteObservationRegistry(
            resolved_database_path,
            actions,
        )
        # 第五步：使用 cls(...) 返回不可变的统一 State，五个字段都要填写。
        return cls(
            database_path=resolved_database_path,
            tasks=tasks,
            task_statuses=task_statuses,
            actions=actions,
            permission_requests=permission_requests,
            permission_decisions=permission_decisions,
            observations=observations,
        )
