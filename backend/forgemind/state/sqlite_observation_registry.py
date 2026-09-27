"""使用 SQLite 保存并恢复每个 Action 的唯一终态 Observation。"""

from pathlib import Path
import sqlite3

from pydantic import TypeAdapter, ValidationError

from forgemind.schema.observations import TerminalObservation
from forgemind.state.observation_registry import (
    DuplicateObservationError,
    UnknownActionIdError,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_permission_request_registry import (
    SQLiteRegistryDatabaseMismatchError,
)


_OBSERVATION_ADAPTER = TypeAdapter(TerminalObservation)


class CorruptStoredObservationError(RuntimeError):
    """磁盘记录无法通过当前 TerminalObservation 严格契约。"""

    def __init__(
        self,
        action_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.action_id = action_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(f"持久化 Observation 无法解析：{action_id}")


class SQLiteObservationRegistry:
    """跨进程保存每个 Action 唯一终态的 SQLite Registry。"""

    def __init__(
        self,
        database_path: Path,
        actions: SQLiteActionRegistry,
    ) -> None:
        self._database_path = database_path
        self._actions = actions

        if database_path.resolve() != actions.database_path.resolve():
            raise SQLiteRegistryDatabaseMismatchError(
                "Observation 和 Action Registry 必须使用同一个数据库"
            )

        with sqlite3.connect(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    action_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES actions(action_id)
                )
                """
            )

    def record(self, observation: TerminalObservation) -> None:
        """为已持久化 Action 追加唯一终态事实。"""

        # 第一步：从 self._actions 读取 observation.action_id；KeyError
        # 转成 UnknownActionIdError(action_id) from None。
        try:
            self._actions.get(observation.action_id)
        except KeyError:
            raise UnknownActionIdError(
                observation.action_id
            ) from None
        # 第二步：把 Observation 序列化为 payload_json。
        payload_json = observation.model_dump_json()
        # 第三步：在事务中启用 foreign_keys，用参数化 INSERT 写入
        # action_id、status、payload_json。
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute(
                    """
                    INSERT INTO observations (
                        action_id,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        observation.action_id,
                        observation.status,
                        payload_json,
                    ),
                )
        # 第四步：重复主键不能覆盖首次终态事实。
        except sqlite3.IntegrityError:
            raise DuplicateObservationError(
                observation.action_id
            ) from None

    def get(self, action_id: str) -> TerminalObservation:
        """按 action_id 严格恢复唯一终态 Observation。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT status, payload_json
                FROM observations
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()

        if row is None:
            raise KeyError(action_id)

        status, payload_json = row
        try:
            observation = _OBSERVATION_ADAPTER.validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredObservationError(action_id, exc) from exc

        if (
            observation.action_id != action_id
            or observation.status != status
        ):
            raise CorruptStoredObservationError(action_id)

        return observation
