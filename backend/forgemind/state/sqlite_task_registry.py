"""使用 SQLite 保存任务创建时不可覆盖的来源事实。"""

from pathlib import Path
import sqlite3

from pydantic import ValidationError

from forgemind.schema.tasks import TaskRecord
from forgemind.state.sqlite_connection import open_sqlite_connection


class DuplicateTaskIdError(ValueError):
    """同一个 task_id 已经登记，旧任务不能被覆盖。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"task_id 已存在：{task_id}")


class UnknownTaskIdError(KeyError):
    """Action 引用的 task_id 尚未登记。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(task_id)


class CorruptStoredTaskError(RuntimeError):
    """磁盘任务无法通过严格契约或索引列一致性检查。"""

    def __init__(
        self,
        task_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.task_id = task_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(f"持久化 Task 无法解析：{task_id}")


class SQLiteTaskRegistry:
    """跨进程保存不可覆盖的 TaskRecord。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

        with open_sqlite_connection(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    project_root TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    @property
    def database_path(self) -> Path:
        """返回 Registry 使用的数据库路径。"""

        return self._database_path

    def register(self, task: TaskRecord) -> None:
        """在一个事务中追加任务；重复编号不能覆盖原记录。"""

        # 第一步：调用 task.model_dump_json() 得到完整 JSON。
        payload_json = task.model_dump_json()
        # 第二步：在 sqlite3.connect(...) 的 with 事务中执行参数化 INSERT，
        # 写入 task_id、project_root、payload_json；不能拼接 SQL 字符串。
        try:
            with open_sqlite_connection(self._database_path) as connection:
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
                        payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            raise DuplicateTaskIdError(task.task_id) from None
        # 第三步：捕获 sqlite3.IntegrityError，转换成
        # DuplicateTaskIdError(task.task_id) from None。

    def get(self, task_id: str) -> TaskRecord:
        """按编号恢复任务，并核对独立索引列与 JSON。"""

        with open_sqlite_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT project_root, payload_json
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()

        if row is None:
            raise KeyError(task_id)

        project_root, payload_json = row
        return self._restore(task_id, project_root, payload_json)

    def list_recent(self, limit: int) -> tuple[TaskRecord, ...]:
        """按 SQLite 插入顺序返回最近创建的任务。"""

        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        with open_sqlite_connection(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT task_id, project_root, payload_json
                FROM tasks
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            self._restore(task_id, project_root, payload_json)
            for task_id, project_root, payload_json in rows
        )

    @staticmethod
    def _restore(task_id: str, project_root: str, payload_json: str) -> TaskRecord:
        """解析存储 JSON，并核对不可独立篡改的索引列。"""

        try:
            task = TaskRecord.model_validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredTaskError(task_id, exc) from exc

        if task.task_id != task_id or task.project_root != project_root:
            raise CorruptStoredTaskError(task_id)

        return task
