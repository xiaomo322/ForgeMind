"""使用 SQLite 保存连续、不可覆盖的任务状态历史。"""

from pathlib import Path
import sqlite3

from pydantic import ValidationError

from forgemind.runtime.task_status import require_task_status_transition
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_connection import open_sqlite_connection
from forgemind.state.sqlite_task_registry import UnknownTaskIdError


class InvalidInitialTaskStatusError(ValueError):
    """任务的第一条状态必须是 revision=1 的 RUNNING。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"任务初始状态无效：{task_id}")


class NonSequentialTaskStatusRevisionError(ValueError):
    """新状态 revision 没有紧接上一条记录。"""

    def __init__(self, task_id: str, expected: int, actual: int) -> None:
        self.task_id = task_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"任务状态版本不连续：{task_id}，应为 {expected}，实际 {actual}"
        )


class DuplicateTaskStatusIdError(ValueError):
    """task_status_id 已存在，旧状态记录不能覆盖。"""

    def __init__(self, task_status_id: str) -> None:
        self.task_status_id = task_status_id
        super().__init__(f"task_status_id 已存在：{task_status_id}")


class CorruptStoredTaskStatusError(RuntimeError):
    """磁盘状态无法通过严格契约或索引列一致性检查。"""

    def __init__(
        self,
        task_status_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.task_status_id = task_status_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(f"持久化任务状态无法解析：{task_status_id}")


class SQLiteTaskStatusRegistry:
    """追加 TaskStatusRecord，并返回任务当前的最高 revision。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

        with open_sqlite_connection(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_statuses (
                    task_status_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (task_id, revision),
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
                """
            )

    @property
    def database_path(self) -> Path:
        return self._database_path

    def record(self, status_record: TaskStatusRecord) -> None:
        """核对任务、revision 和转换规则后追加一条状态。"""

        payload_json = status_record.model_dump_json()

        try:
            with open_sqlite_connection(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                # 先取得写锁，再读取上一版本，避免两个写入者同时看到
                # 相同 revision 后都认为自己可以追加下一条。
                connection.execute("BEGIN IMMEDIATE")

                task_row = connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?",
                    (status_record.task_id,),
                ).fetchone()
                if task_row is None:
                    raise UnknownTaskIdError(status_record.task_id)

                latest_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (status_record.task_id,),
                ).fetchone()

                # 第一步：latest_row 为 None 时，这是第一条状态；要求
                # revision == 1 且 status is TaskStatus.RUNNING，否则抛出
                # InvalidInitialTaskStatusError(task_id)。
                if latest_row is None:
                    if (
                        status_record.revision != 1
                        or
                        status_record.status is not TaskStatus.RUNNING
                    ):
                        raise InvalidInitialTaskStatusError(
                            status_record.task_id
                        )
                # 第二步：已有状态时，计算 expected_revision = 上一版本 + 1；
                # 不相等则抛出 NonSequentialTaskStatusRevisionError，错误中
                # 填入 task_id、expected_revision、实际 revision。

                else:
                    latest_status_id, *latest_stored_record = latest_row
                    latest_record = self._restore(
                        latest_status_id,
                        latest_stored_record,
                    )
                    expected_revision = latest_record.revision + 1

                # 第三步：revision 正确后，把 latest_row 的 status 字符串
                # 转为 TaskStatus，并调用 require_task_status_transition。
                    if status_record.revision != expected_revision:
                        raise NonSequentialTaskStatusRevisionError(
                            status_record.task_id,
                            expected_revision,
                            status_record.revision,
                        )
                    require_task_status_transition(
                        latest_record.status,
                        status_record.status,
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
                        status_record.task_status_id,
                        status_record.task_id,
                        status_record.revision,
                        status_record.status.value,
                        payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            raise DuplicateTaskStatusIdError(
                status_record.task_status_id
            ) from None

    def get(self, task_status_id: str) -> TaskStatusRecord:
        """按状态编号恢复一条严格记录。"""

        with open_sqlite_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT task_id, revision, status, payload_json
                FROM task_statuses
                WHERE task_status_id = ?
                """,
                (task_status_id,),
            ).fetchone()

        if row is None:
            raise KeyError(task_status_id)

        return self._restore(task_status_id, row)

    def get_current(self, task_id: str) -> TaskStatusRecord:
        """恢复任务最高 revision 的当前状态。"""

        with open_sqlite_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT task_status_id, task_id, revision, status, payload_json
                FROM task_statuses
                WHERE task_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()

        if row is None:
            raise KeyError(task_id)

        task_status_id, *stored_record = row
        return self._restore(task_status_id, stored_record)

    @staticmethod
    def _restore(
        task_status_id: str,
        row: tuple[object, ...] | list[object],
    ) -> TaskStatusRecord:
        task_id, revision, status, payload_json = row
        try:
            record = TaskStatusRecord.model_validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredTaskStatusError(
                task_status_id,
                exc,
            ) from exc

        if (
            record.task_status_id != task_status_id
            or record.task_id != task_id
            or record.revision != revision
            or record.status.value != status
        ):
            raise CorruptStoredTaskStatusError(task_status_id)

        return record
