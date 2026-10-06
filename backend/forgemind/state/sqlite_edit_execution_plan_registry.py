"""使用 SQLite 保存 edit_file 的可恢复执行计划。"""

from pathlib import Path
import sqlite3

from pydantic import ValidationError

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.execution import EditExecutionPlan
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_connection import open_sqlite_connection
from forgemind.state.sqlite_permission_request_registry import (
    SQLiteRegistryDatabaseMismatchError,
)


class UnknownEditExecutionActionError(KeyError):
    """执行计划引用的 Action 尚未持久化。"""


class EditExecutionPlanActionSnapshotMismatchError(ValueError):
    """执行计划没有忠实引用对应 edit_file Action。"""


class DuplicateEditExecutionPlanError(ValueError):
    """一个 Action 已经拥有不可覆盖的执行计划。"""


class CorruptStoredEditExecutionPlanError(RuntimeError):
    """磁盘计划无法通过严格 Schema 或索引列交叉校验。"""

    def __init__(
        self,
        action_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.action_id = action_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(f"持久化 edit_file 执行计划无法解析：{action_id}")


class SQLiteEditExecutionPlanRegistry:
    """按 action_id 持久化一份 edit_file 对账计划。"""

    def __init__(
        self,
        database_path: Path,
        actions: SQLiteActionRegistry,
    ) -> None:
        self._database_path = database_path
        self._actions = actions
        if database_path.resolve() != actions.database_path.resolve():
            raise SQLiteRegistryDatabaseMismatchError(
                "EditExecutionPlan 和 Action Registry 必须使用同一个数据库"
            )

        with open_sqlite_connection(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS edit_execution_plans (
                    action_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    before_version TEXT NOT NULL,
                    after_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES actions(action_id)
                )
                """
            )

    @property
    def database_path(self) -> Path:
        return self._database_path

    @staticmethod
    def validate_action_snapshot(
        plan: EditExecutionPlan,
        action: object,
    ) -> None:
        """确认计划来自同一条、同一版本的 edit_file Action。"""

        if (
            not isinstance(action, AcceptedEditFileToolAction)
            or plan.task_id != action.task_id
            or plan.path != action.arguments.path
            or plan.before_version != action.arguments.expected_version
        ):
            raise EditExecutionPlanActionSnapshotMismatchError(plan.action_id)

    def register(self, plan: EditExecutionPlan) -> None:
        try:
            action = self._actions.get(plan.action_id)
        except KeyError:
            raise UnknownEditExecutionActionError(plan.action_id) from None
        self.validate_action_snapshot(plan, action)

        try:
            with open_sqlite_connection(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                self.insert(connection, plan)
        except sqlite3.IntegrityError:
            raise DuplicateEditExecutionPlanError(plan.action_id) from None

    @staticmethod
    def insert(connection: sqlite3.Connection, plan: EditExecutionPlan) -> None:
        """在调用方控制的事务中插入计划。"""

        connection.execute(
            """
            INSERT INTO edit_execution_plans (
                action_id, task_id, path, before_version,
                after_version, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                plan.action_id,
                plan.task_id,
                plan.path,
                plan.before_version,
                plan.after_version,
                plan.model_dump_json(),
            ),
        )

    def get(self, action_id: str) -> EditExecutionPlan:
        with open_sqlite_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT task_id, path, before_version, after_version, payload_json
                FROM edit_execution_plans
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
        if row is None:
            raise KeyError(action_id)

        task_id, path, before_version, after_version, payload_json = row
        try:
            plan = EditExecutionPlan.model_validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredEditExecutionPlanError(action_id, exc) from exc
        if (
            plan.action_id != action_id
            or plan.task_id != task_id
            or plan.path != path
            or plan.before_version != before_version
            or plan.after_version != after_version
        ):
            raise CorruptStoredEditExecutionPlanError(action_id)
        return plan

    def get_optional(self, action_id: str) -> EditExecutionPlan | None:
        try:
            return self.get(action_id)
        except KeyError:
            return None
