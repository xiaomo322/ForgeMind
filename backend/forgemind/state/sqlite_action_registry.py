"""使用 SQLite 保存并恢复不可覆盖的 AcceptedAction。"""

from pathlib import Path
import sqlite3

from pydantic import TypeAdapter, ValidationError

from forgemind.schema.actions import AcceptedToolAction
from forgemind.state.action_registry import DuplicateActionIdError
from forgemind.state.sqlite_task_registry import UnknownTaskIdError


_ACTION_ADAPTER = TypeAdapter(AcceptedToolAction)


class CorruptStoredActionError(RuntimeError):
    """磁盘记录无法通过当前 AcceptedToolAction 严格契约。"""

    def __init__(self, action_id: str, cause: ValidationError) -> None:
        self.action_id = action_id
        self.error_count = cause.error_count()
        super().__init__(f"持久化 Action 无法解析：{action_id}")


class SQLiteActionRegistry:
    """跨进程保存 AcceptedAction 的 SQLite Registry。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

        # 建表本身也在事务中完成。action_id 主键把内存 Registry 的
        # “同一编号不可覆盖”规则下沉到磁盘层。
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
                """
            )

    @property
    def database_path(self) -> Path:
        """返回该 Registry 使用的数据库路径，供关联 Registry 核对。"""

        return self._database_path

    def register(self, action: AcceptedToolAction) -> None:
        """在一个事务中追加 Action；重复编号不能覆盖原记录。"""

        # 第一步：调用 action.model_dump_json() 得到严格模型的 JSON。
        payload_json = action.model_dump_json()

        try:
            # 第二步：用 sqlite3.connect 打开数据库，并在 with 事务中执行：
            # INSERT INTO actions (action_id, task_id, tool_name, payload_json)
            # VALUES (?, ?, ?, ?)
            # 参数必须单独传入，不能拼接 SQL 字符串。
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")

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
                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id,
                        task_id,
                        tool_name,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        action.action_id,
                        action.task_id,
                        action.tool_name,
                        payload_json,
                    ),
                )
        # 第四步：捕获 sqlite3.IntegrityError，把主键冲突转换为现有的
        # DuplicateActionIdError，并用 ``from None`` 隐藏数据库细节。
        except sqlite3.IntegrityError:
            raise DuplicateActionIdError(action.action_id) from None

    def get(self, action_id: str) -> AcceptedToolAction:
        """按编号读取 JSON，并通过严格联合类型重建 Action。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()

        if row is None:
            raise KeyError(action_id)

        try:
            return _ACTION_ADAPTER.validate_json(row[0])
        except ValidationError as exc:
            raise CorruptStoredActionError(action_id, exc) from exc
