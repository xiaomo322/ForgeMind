"""把同一数据库中的四个 SQLite Registry 组合成统一入口。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Self

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
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry
from forgemind.state.sqlite_task_status_registry import (
    SQLiteTaskStatusRegistry,
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
