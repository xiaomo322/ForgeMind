"""使用 SQLite 保存并恢复不可覆盖的 AcceptedAction。"""

from pathlib import Path
import sqlite3

from pydantic import TypeAdapter, ValidationError

from forgemind.schema.actions import AcceptedAction, SequencedActionRecord
from forgemind.state.action_registry import DuplicateActionIdError
from forgemind.state.sqlite_connection import open_sqlite_connection
from forgemind.state.sqlite_task_registry import UnknownTaskIdError


_ACTION_ADAPTER = TypeAdapter(AcceptedAction)


class CorruptStoredActionError(RuntimeError):
    """磁盘记录无法通过当前 AcceptedToolAction 严格契约。"""

    def __init__(
        self,
        action_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.action_id = action_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(f"持久化 Action 无法解析：{action_id}")


class SQLiteActionRegistry:
    """跨进程保存 AcceptedAction 的 SQLite Registry。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

        with open_sqlite_connection(self._database_path) as connection:
            # 第一步：执行 PRAGMA table_info(actions)，并调用 fetchall()
            # 得到 columns。
            columns = connection.execute(
                "PRAGMA table_info(actions)"
            ).fetchall()

            # 第二步：如果 columns 为空，调用
            # self._create_actions_table(connection) 创建新版空表。
            if not columns:
                self._create_actions_table(connection)
            else:
                column_names = {
                    row[1] for row in columns
                }
                if "action_type" not in column_names:
                    self._migrate_legacy_actions_table(connection)

            # 第三步：否则取得所有 row[1] 组成的列名集合；如果集合中没有
            # "action_type"，调用 self._migrate_legacy_actions_table(connection)。
            # 已经存在 action_type 时不执行任何迁移。

    @staticmethod
    def _create_actions_table(connection: sqlite3.Connection) -> None:
        """创建能够保存所有 AcceptedAction 的新版空表。"""

        connection.execute(
            """
            CREATE TABLE actions (
                action_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_sequence INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                tool_name TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE (task_id, task_sequence),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
            """
        )

    @staticmethod
    def _migrate_legacy_actions_table(
        connection: sqlite3.Connection,
    ) -> None:
        """把 Tool 专用旧表原子迁移为通用 Action 表。"""

        # 第一步：迁移期间先取得写事务，复制、替换表必须整体成功或回滚。
        connection.execute("BEGIN IMMEDIATE")

        # 第二步：创建临时新版表。暂时不用 actions 名称，避免与旧表冲突。
        connection.execute(
            """
            CREATE TABLE actions_v2 (
                action_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_sequence INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                tool_name TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE (task_id, task_sequence),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
            """
        )

        # 第三步：复制旧表的全部事实。旧 Registry 只允许 Tool Action，
        # 因此新增 action_type 使用确定的字面值 tool_call。
        connection.execute(
            """
            INSERT INTO actions_v2 (
                action_id,
                task_id,
                task_sequence,
                action_type,
                tool_name,
                payload_json
            )
            SELECT
                action_id,
                task_id,
                task_sequence,
                'tool_call',
                tool_name,
                payload_json
            FROM actions
            """
        )

        # 第四步：只有复制成功后才删除旧表，再把临时表改为正式名称。
        connection.execute("DROP TABLE actions")
        connection.execute("ALTER TABLE actions_v2 RENAME TO actions")

    @property
    def database_path(self) -> Path:
        """返回该 Registry 使用的数据库路径，供关联 Registry 核对。"""

        return self._database_path

    def register(self, action: AcceptedAction) -> None:
        """在一个事务中追加 Action；重复编号不能覆盖原记录。"""

        # 第一步：调用 action.model_dump_json() 得到严格模型的 JSON。
        payload_json = action.model_dump_json()

        # 第一步：如果 action.action_type 是 "tool_call"，tool_name 使用
        # action.tool_name；否则它必须为 None，数据库会保存为 SQL NULL。
        # 请在这里实现并得到局部变量 tool_name。
        if action.action_type == "tool_call":
            tool_name = action.tool_name
        else:
            tool_name = None

        try:
            # 第二步：用 sqlite3.connect 打开数据库，并在 with 事务中执行：
            # INSERT INTO actions (action_id, task_id, tool_name, payload_json)
            # VALUES (?, ?, ?, ?)
            # 参数必须单独传入，不能拼接 SQL 字符串。
            with open_sqlite_connection(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                # 第三步：在同一个事务中查询 tasks 表，确认
                # action.task_id 已经登记；不存在时抛出
                # UnknownTaskIdError(action.task_id)。
                task_row = connection.execute(
                    """
                    SELECT 1
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (action.task_id,),
                ).fetchone()

                if task_row is None:
                    raise UnknownTaskIdError(action.task_id)

                # 第四步：查询该 task_id 当前最大的 task_sequence；没有
                # Action 时从 1 开始，否则使用最大值 + 1。保存为
                # next_sequence，查询和 INSERT 必须留在同一写事务中。
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
                        tool_name,
                        payload_json,
                    ),
                )
        # 第五步：捕获 sqlite3.IntegrityError，把主键冲突转换为现有的
        # DuplicateActionIdError，并用 ``from None`` 隐藏数据库细节。
        except sqlite3.IntegrityError:
            raise DuplicateActionIdError(action.action_id) from None

    def get(self, action_id: str) -> AcceptedAction:
        """按编号读取 JSON，并通过严格联合类型重建 Action。"""

        with open_sqlite_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT task_id, action_type, tool_name, payload_json
                FROM actions
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()

        if row is None:
            raise KeyError(action_id)

        return self._restore(action_id, row[0], row[1], row[2], row[3])

    def list_for_task(self, task_id: str) -> tuple[SequencedActionRecord, ...]:
        """按 State 分配的任务内序号返回 Action，不按随机 ID 排序。"""

        with open_sqlite_connection(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    action_id,
                    task_sequence,
                    task_id,
                    action_type,
                    tool_name,
                    payload_json
                FROM actions
                WHERE task_id = ?
                ORDER BY task_sequence
                """,
                (task_id,),
            ).fetchall()

        return tuple(
            SequencedActionRecord(
                sequence=sequence,
                action=self._restore(
                    action_id,
                    stored_task_id,
                    stored_action_type,
                    stored_tool_name,
                    payload_json,
                ),
            )
            for (
                action_id,
                sequence,
                stored_task_id,
                stored_action_type,
                stored_tool_name,
                payload_json,
            ) in rows
        )

    @staticmethod
    def _restore(
        action_id: str,
        stored_task_id: str,
        stored_action_type: str,
        stored_tool_name: str | None,
        payload_json: str,
    ) -> AcceptedAction:
        try:
            action = _ACTION_ADAPTER.validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredActionError(action_id, exc) from exc

        # 第二步：先核对 action_id、task_id、action_type。然后按类型核对：
        # Tool Action 的 action.tool_name 必须等于 stored_tool_name；
        # AskUserAction 的 stored_tool_name 必须为 None。任何不一致都抛出
        # CorruptStoredActionError(action_id)。请替换当前临时判断。
        if (
            action.action_id != action_id
            or action.task_id != stored_task_id
            or action.action_type != stored_action_type
            or (
                action.action_type == "tool_call"
                and action.tool_name != stored_tool_name
            )
            or (action.action_type != "tool_call" and stored_tool_name is not None)
        ):
            raise CorruptStoredActionError(action_id)

        return action
