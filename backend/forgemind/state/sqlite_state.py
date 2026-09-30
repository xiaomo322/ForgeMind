"""把同一数据库中的四个 SQLite Registry 组合成统一入口。"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Self

from forgemind.runtime.task_status import require_task_status_transition
from forgemind.runtime.user_responses import validate_user_response_for_question
from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import (
    ActionStateView,
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.action_registry import DuplicateActionIdError
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
    NonSequentialTaskStatusRevisionError,
    SQLiteTaskStatusRegistry,
)
from forgemind.state.sqlite_user_response_registry import (
    SQLiteUserResponseRegistry,
)
from forgemind.state.user_response_registry import (
    DuplicateQuestionResponseError,
    DuplicateUserResponseIdError,
    QuestionActionTypeError,
    UnknownQuestionActionIdError,
)


class TaskStatusTaskMismatchError(ValueError):
    """初始状态没有引用即将创建的同一个任务。"""

    def __init__(self, task_id: str, status_task_id: str) -> None:
        self.task_id = task_id
        self.status_task_id = status_task_id
        super().__init__(
            f"任务与初始状态不匹配：{task_id} != {status_task_id}"
        )


class AskUserWaitingTaskMismatchError(ValueError):
    """询问 Action 与等待状态没有引用同一任务。"""


class InvalidAskUserWaitingStatusError(ValueError):
    """询问 Action 只能与 WAITING_USER 状态一起登记。"""


class UserAnswerStatusTaskMismatchError(ValueError):
    """用户回答与恢复状态没有引用同一任务。"""


class InvalidUserAnswerTypeError(ValueError):
    """回答恢复流程只接受 ANSWER，不处理 CANCEL。"""


class InvalidUserAnswerRunningStatusError(ValueError):
    """有效回答只能与新的 RUNNING 状态一起登记。"""


class UserAnswerRequiresWaitingStatusError(ValueError):
    """只有当前处于 WAITING_USER 的任务才能由回答恢复。"""


class UserAnswerQuestionNotCurrentError(ValueError):
    """回答引用的不是当前等待的最新询问。"""


@dataclass(frozen=True, slots=True)
class SQLiteForgeMindState:
    """持有一组连接到同一数据库且依赖关系正确的 Registry。"""
    database_path: Path
    tasks: SQLiteTaskRegistry
    task_statuses: SQLiteTaskStatusRegistry
    actions: SQLiteActionRegistry
    user_responses: SQLiteUserResponseRegistry
    permission_requests: SQLitePermissionRequestRegistry
    permission_decisions: SQLitePermissionDecisionRegistry
    observations: SQLiteObservationRegistry

    def record_ask_user_waiting(
        self,
        action: AcceptedAskUserAction,
        waiting_status: TaskStatusRecord,
    ) -> None:
        """原子登记询问 Action 和对应的 WAITING_USER 状态。"""

        if action.task_id != waiting_status.task_id:
            raise AskUserWaitingTaskMismatchError
        if waiting_status.status is not TaskStatus.WAITING_USER:
            raise InvalidAskUserWaitingStatusError

        action_payload_json = action.model_dump_json()
        status_payload_json = waiting_status.model_dump_json()

        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                task_row = connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?",
                    (action.task_id,),
                ).fetchone()
                if task_row is None:
                    from forgemind.state.sqlite_task_registry import (
                        UnknownTaskIdError,
                    )

                    raise UnknownTaskIdError(action.task_id)

                latest_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if latest_row is None:
                    raise KeyError(action.task_id)

                latest_status_id, *latest_stored_record = latest_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    latest_stored_record,
                )
                expected_revision = current.revision + 1
                if waiting_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        action.task_id,
                        expected_revision,
                        waiting_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    waiting_status.status,
                )

                sequence_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(task_sequence), 0) + 1
                    FROM actions
                    WHERE task_id = ?
                    """,
                    (action.task_id,),
                ).fetchone()
                next_sequence = sequence_row[0]

                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id,
                        task_id,
                        task_sequence,
                        action_type,
                        tool_name,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.action_id,
                        action.task_id,
                        next_sequence,
                        action.action_type,
                        None,
                        action_payload_json,
                    ),
                )
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
                        waiting_status.task_status_id,
                        waiting_status.task_id,
                        waiting_status.revision,
                        waiting_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_ask_user_waiting_conflict(action, waiting_status)

    def _raise_ask_user_waiting_conflict(
        self,
        action: AcceptedAskUserAction,
        waiting_status: TaskStatusRecord,
    ) -> None:
        """事务回滚后把唯一约束冲突转换为稳定领域错误。"""

        with sqlite3.connect(self.database_path) as connection:
            action_exists = connection.execute(
                "SELECT 1 FROM actions WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (waiting_status.task_status_id,),
            ).fetchone()

        if action_exists is not None:
            raise DuplicateActionIdError(action.action_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                waiting_status.task_status_id
            ) from None
        raise RuntimeError("询问等待记录违反未知的 SQLite 完整性约束")

    def record_user_answer_running(
        self,
        response: UserResponseRecord,
        running_status: TaskStatusRecord,
    ) -> None:
        """原子保存有效回答并把任务从等待恢复为运行。"""

        if response.task_id != running_status.task_id:
            raise UserAnswerStatusTaskMismatchError
        if response.response_type is not UserResponseType.ANSWER:
            raise InvalidUserAnswerTypeError
        if running_status.status is not TaskStatus.RUNNING:
            raise InvalidUserAnswerRunningStatusError

        try:
            question = self.actions.get(response.question_action_id)
        except KeyError:
            raise UnknownQuestionActionIdError(
                response.question_action_id
            ) from None
        if not isinstance(question, AcceptedAskUserAction):
            raise QuestionActionTypeError(response.question_action_id)
        validate_user_response_for_question(response, question)

        response_payload_json = response.model_dump_json()
        status_payload_json = running_status.model_dump_json()

        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (response.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(response.task_id)

                latest_status_id, *latest_stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    latest_stored_status,
                )
                if current.status is not TaskStatus.WAITING_USER:
                    raise UserAnswerRequiresWaitingStatusError

                expected_revision = current.revision + 1
                if running_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        response.task_id,
                        expected_revision,
                        running_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    running_status.status,
                )

                latest_action_row = connection.execute(
                    """
                    SELECT action_id
                    FROM actions
                    WHERE task_id = ?
                    ORDER BY task_sequence DESC
                    LIMIT 1
                    """,
                    (response.task_id,),
                ).fetchone()
                if (
                    latest_action_row is None
                    or latest_action_row[0] != response.question_action_id
                ):
                    raise UserAnswerQuestionNotCurrentError

                connection.execute(
                    """
                    INSERT INTO user_responses (
                        response_id,
                        question_action_id,
                        task_id,
                        response_type,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        response.response_id,
                        response.question_action_id,
                        response.task_id,
                        response.response_type.value,
                        response_payload_json,
                    ),
                )
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
                        running_status.task_status_id,
                        running_status.task_id,
                        running_status.revision,
                        running_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_user_answer_running_conflict(
                response,
                running_status,
            )

    def _raise_user_answer_running_conflict(
        self,
        response: UserResponseRecord,
        running_status: TaskStatusRecord,
    ) -> None:
        """事务回滚后把唯一约束冲突转为稳定领域错误。"""

        with sqlite3.connect(self.database_path) as connection:
            response_id_exists = connection.execute(
                "SELECT 1 FROM user_responses WHERE response_id = ?",
                (response.response_id,),
            ).fetchone()
            question_response_exists = connection.execute(
                "SELECT 1 FROM user_responses WHERE question_action_id = ?",
                (response.question_action_id,),
            ).fetchone()
            status_id_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (running_status.task_status_id,),
            ).fetchone()

        if response_id_exists is not None:
            raise DuplicateUserResponseIdError(response.response_id) from None
        if question_response_exists is not None:
            raise DuplicateQuestionResponseError(
                response.question_action_id
            ) from None
        if status_id_exists is not None:
            raise DuplicateTaskStatusIdError(
                running_status.task_status_id
            ) from None
        raise RuntimeError("用户回答恢复违反未知的 SQLite 完整性约束")

    def get_task_view(self, task_id: str) -> TaskStateView:
        """组合不可变任务来源、当前状态和有序 Action 历史。"""

        action_records = self.actions.list_for_task(task_id)
        action_states: list[ActionStateView] = []

        for record in action_records:
            if record.action.action_type == "ask_user":
                user_response = (
                    self.user_responses.get_optional_for_question(
                        record.action.action_id
                    )
                )
            else:
                user_response = None

            # 第一步：使用 record.action.action_id 调用
            # self.permission_requests.get_optional_for_action(...)，保存为
            # permission_request。
            permission_request = (
                self.permission_requests.get_optional_for_action(
                    record.action.action_id
                )
            )
            # 第二步：如果 permission_request 为 None，
            # permission_decision 也设为 None；否则使用请求编号调用
            # self.permission_decisions.get_optional_for_request(...)。
            if permission_request is None:
                permission_decision = None
            else:
                permission_decision = (
                    self.permission_decisions.get_optional_for_request(
                        permission_request.permission_request_id
                    )
                )
            # 第三步：构造 ActionStateView，把 sequence、action、权限请求、
            # 权限决定和按 action_id 查询的 Observation 全部传入，再追加到
            # action_states。
            action_states.append(
                ActionStateView(
                    sequence=record.sequence,
                    action=record.action,
                    user_response=user_response,
                    permission_request=permission_request,
                    permission_decision=permission_decision,
                    observation=self.observations.get_optional(
                        record.action.action_id
                    ),
                )
            )

        return TaskStateView(
            task=self.tasks.get(task_id),
            current_status=self.task_statuses.get_current(task_id),
            actions=tuple(action_states),
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
        user_responses = SQLiteUserResponseRegistry(
            resolved_database_path,
            actions,
        )
        # 第二步：用 resolved_database_path 和 actions 创建
        # SQLiteUserResponseRegistry，保存为 user_responses。
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
            user_responses=user_responses,
            permission_requests=permission_requests,
            permission_decisions=permission_decisions,
            observations=observations,
        )
