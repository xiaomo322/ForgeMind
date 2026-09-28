"""使用 SQLite 保存并恢复用户的最终权限决定。"""

from pathlib import Path
import sqlite3

from pydantic import ValidationError

from forgemind.schema.permissions import PermissionDecisionRecord
from forgemind.state.permission_decision_registry import (
    DuplicatePermissionDecisionIdError,
    DuplicatePermissionRequestDecisionError,
    PermissionDecisionRequestMismatchError,
    UnknownPermissionRequestIdError,
)
from forgemind.state.sqlite_permission_request_registry import (
    SQLitePermissionRequestRegistry,
    SQLiteRegistryDatabaseMismatchError,
)


class CorruptStoredPermissionDecisionError(RuntimeError):
    """磁盘记录无法通过当前 PermissionDecisionRecord 严格契约。"""

    def __init__(
        self,
        permission_decision_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.permission_decision_id = permission_decision_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(
            f"持久化权限决定无法解析：{permission_decision_id}"
        )


class SQLitePermissionDecisionRegistry:
    """跨进程保存 PermissionDecisionRecord 的 SQLite Registry。"""

    def __init__(
        self,
        database_path: Path,
        requests: SQLitePermissionRequestRegistry,
    ) -> None:
        self._database_path = database_path
        self._requests = requests

        if database_path.resolve() != requests.database_path.resolve():
            raise SQLiteRegistryDatabaseMismatchError(
                "权限决定和权限请求 Registry 必须使用同一个数据库"
            )

        with sqlite3.connect(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS permission_decisions (
                    permission_decision_id TEXT PRIMARY KEY,
                    permission_request_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (permission_request_id)
                        REFERENCES permission_requests(permission_request_id),
                    FOREIGN KEY (action_id) REFERENCES actions(action_id)
                )
                """
            )

    def record(self, decision: PermissionDecisionRecord) -> None:
        """核对原始询问后，追加唯一最终决定。"""

        # 第一步：按 permission_request_id 从 self._requests 恢复原询问；
        # KeyError 转成 UnknownPermissionRequestIdError(... ) from None。
        try:
            request = self._requests.get(decision.permission_request_id)
        except KeyError:
            raise UnknownPermissionRequestIdError(
                decision.permission_request_id
            ) from None
        # 第二步：核对 task_id 和 action_id；不一致抛出
        # PermissionDecisionRequestMismatchError(permission_request_id)。
        if (
            decision.task_id != request.task_id
            or decision.action_id != request.action_id
        ):
            raise PermissionDecisionRequestMismatchError(
                decision.permission_request_id
            )

        payload_json = decision.model_dump_json()

        # 第三步：序列化 decision，并在事务中启用 foreign_keys 后 INSERT。
        with sqlite3.connect(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            try:
                connection.execute(
                    """
                    INSERT INTO permission_decisions (
                        permission_decision_id,
                        permission_request_id,
                        task_id,
                        action_id,
                        decision,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.permission_decision_id,
                        decision.permission_request_id,
                        decision.task_id,
                        decision.action_id,
                        decision.decision.value,
                        payload_json,
                    ),
                )
            # 第四步：IntegrityError 后查询冲突来源；两种情况都不能
            # 覆盖磁盘中的第一次用户回答。
            except sqlite3.IntegrityError:
                duplicate_id = connection.execute(
                    """
                    SELECT 1
                    FROM permission_decisions
                    WHERE permission_decision_id = ?
                    """,
                    (decision.permission_decision_id,),
                ).fetchone()

                if duplicate_id is not None:
                    raise DuplicatePermissionDecisionIdError(
                        decision.permission_decision_id
                    ) from None

                raise DuplicatePermissionRequestDecisionError(
                    decision.permission_request_id
                ) from None

    def get(self, permission_decision_id: str) -> PermissionDecisionRecord:
        """按决定编号严格恢复记录。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT permission_request_id, task_id, action_id,
                       decision, payload_json
                FROM permission_decisions
                WHERE permission_decision_id = ?
                """,
                (permission_decision_id,),
            ).fetchone()

        if row is None:
            raise KeyError(permission_decision_id)

        request_id, task_id, action_id, decision_value, payload_json = row
        try:
            decision = PermissionDecisionRecord.model_validate_json(
                payload_json
            )
        except ValidationError as exc:
            raise CorruptStoredPermissionDecisionError(
                permission_decision_id,
                exc,
            ) from exc

        if (
            decision.permission_decision_id != permission_decision_id
            or decision.permission_request_id != request_id
            or decision.task_id != task_id
            or decision.action_id != action_id
            or decision.decision.value != decision_value
        ):
            raise CorruptStoredPermissionDecisionError(
                permission_decision_id
            )

        return decision

    def get_for_request(
        self,
        permission_request_id: str,
    ) -> PermissionDecisionRecord:
        """按询问编号恢复它唯一的最终用户决定。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT permission_decision_id
                FROM permission_decisions
                WHERE permission_request_id = ?
                """,
                (permission_request_id,),
            ).fetchone()

        if row is None:
            raise KeyError(permission_request_id)
        return self.get(row[0])

    def get_optional_for_request(
        self,
        permission_request_id: str,
    ) -> PermissionDecisionRecord | None:
        """用户尚未回答时返回 None，损坏记录仍然抛错。"""

        # 第一步：在 try 中调用并返回
        # self.get_for_request(permission_request_id)。
        try:
            return self.get_for_request(permission_request_id)
        # 第二步：只捕获 KeyError 并返回 None。
        except KeyError:
            return None
