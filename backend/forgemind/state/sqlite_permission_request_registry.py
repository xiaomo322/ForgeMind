"""使用 SQLite 保存并恢复等待用户确认的权限请求。"""

from pathlib import Path
import sqlite3

from pydantic import TypeAdapter, ValidationError

from forgemind.schema.permissions import PendingPermissionRequest
from forgemind.state.permission_request_registry import (
    DuplicatePermissionRequestIdError,
    PermissionRequestActionSnapshotMismatchError,
    UnknownPermissionRequestActionError,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry


_REQUEST_ADAPTER = TypeAdapter(PendingPermissionRequest)


class SQLiteRegistryDatabaseMismatchError(ValueError):
    """相互关联的 SQLite Registry 没有使用同一个数据库。"""


class CorruptStoredPermissionRequestError(RuntimeError):
    """磁盘记录无法通过当前 PendingPermissionRequest 严格契约。"""

    def __init__(
        self,
        permission_request_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.permission_request_id = permission_request_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(
            f"持久化权限请求无法解析：{permission_request_id}"
        )


class SQLitePermissionRequestRegistry:
    """跨进程保存 PendingPermissionRequest 的 SQLite Registry。"""

    def __init__(
        self,
        database_path: Path,
        actions: SQLiteActionRegistry,
    ) -> None:
        self._database_path = database_path
        self._actions = actions

        if database_path.resolve() != actions.database_path.resolve():
            raise SQLiteRegistryDatabaseMismatchError(
                "权限请求和 Action Registry 必须使用同一个数据库"
            )

        with sqlite3.connect(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS permission_requests (
                    permission_request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES actions(action_id)
                )
                """
            )

    @property
    def database_path(self) -> Path:
        """返回该 Registry 使用的数据库路径。"""

        return self._database_path

    def register(self, request: PendingPermissionRequest) -> None:
        """核对 Action 快照后，在事务中追加权限请求。"""

        # 第一步：用 request.action_id 从 self._actions 读取权威 Action；
        # KeyError 转成 UnknownPermissionRequestActionError(... ) from None。
        try:
            action = self._actions.get(request.action_id)
        except KeyError:
            raise UnknownPermissionRequestActionError(
                request.action_id
            ) from None
        # 第二步：核对 request 的 task_id、action_type、tool_name、arguments
        # 与 Action 完全一致；不一致抛出快照错误。
        if (
            request.task_id != action.task_id
            or request.action_type != action.action_type
            or request.tool_name != action.tool_name
            or request.arguments != action.arguments
        ):
            raise PermissionRequestActionSnapshotMismatchError(
                request.action_id
            )
        # 第三步：把 request 序列化为 payload_json。
        payload_json = request.model_dump_json()
        # 第四步：事务中先执行 PRAGMA foreign_keys = ON，再用参数化 INSERT
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute(
                    """
                    INSERT INTO permission_requests (
                        permission_request_id,
                        task_id,
                        action_id,
                        tool_name,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        request.permission_request_id,
                        request.task_id,
                        request.action_id,
                        request.tool_name,
                        payload_json,
                    ),
                )
        # 第五步：重复主键不能覆盖已经展示给用户的原始询问。
        except sqlite3.IntegrityError:
            raise DuplicatePermissionRequestIdError(
                request.permission_request_id
            ) from None

    def get(self, permission_request_id: str) -> PendingPermissionRequest:
        """读取并严格恢复一条待确认权限请求。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT task_id, action_id, tool_name, payload_json
                FROM permission_requests
                WHERE permission_request_id = ?
                """,
                (permission_request_id,),
            ).fetchone()

        if row is None:
            raise KeyError(permission_request_id)

        task_id, action_id, tool_name, payload_json = row
        try:
            request = _REQUEST_ADAPTER.validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredPermissionRequestError(
                permission_request_id,
                exc,
            ) from exc

        # 查询列将用于后续索引与外键，必须与完整 JSON 中的事实一致。
        if (
            request.permission_request_id != permission_request_id
            or request.task_id != task_id
            or request.action_id != action_id
            or request.tool_name != tool_name
        ):
            raise CorruptStoredPermissionRequestError(permission_request_id)

        return request
