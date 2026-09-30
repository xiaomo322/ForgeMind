"""使用 SQLite 保存并严格恢复用户回答。"""

from pathlib import Path
import sqlite3

from pydantic import ValidationError

from forgemind.runtime.user_responses import validate_user_response_for_question
from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_permission_request_registry import (
    SQLiteRegistryDatabaseMismatchError,
)
from forgemind.state.user_response_registry import (
    DuplicateQuestionResponseError,
    DuplicateUserResponseIdError,
    QuestionActionTypeError,
    UnknownQuestionActionIdError,
)


class CorruptStoredUserResponseError(RuntimeError):
    """磁盘回答无法通过当前严格契约或索引核对。"""

    def __init__(
        self,
        response_id: str,
        cause: ValidationError | None = None,
    ) -> None:
        self.response_id = response_id
        self.error_count = 0 if cause is None else cause.error_count()
        super().__init__(f"持久化用户回答无法解析：{response_id}")


class SQLiteUserResponseRegistry:
    """跨进程保存 UserResponseRecord 的 SQLite Registry。"""

    def __init__(
        self,
        database_path: Path,
        actions: SQLiteActionRegistry,
    ) -> None:
        self._database_path = database_path
        self._actions = actions

        if database_path.resolve() != actions.database_path.resolve():
            raise SQLiteRegistryDatabaseMismatchError(
                "用户回答和 Action Registry 必须使用同一个数据库"
            )

        with sqlite3.connect(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_responses (
                    response_id TEXT PRIMARY KEY,
                    question_action_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    response_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (question_action_id)
                        REFERENCES actions(action_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
                """
            )

    @property
    def database_path(self) -> Path:
        """返回注册表使用的数据库路径。"""

        return self._database_path

    def record(self, response: UserResponseRecord) -> None:
        """核对原问题后把唯一用户回答追加到磁盘。"""

        # 第一步：根据 response.question_action_id 调用
        # self._actions.get()。KeyError 必须转换为
        # UnknownQuestionActionIdError(... ) from None。
        try:
            question = self._actions.get(response.question_action_id)
        except KeyError:
            raise UnknownQuestionActionIdError(
                response.question_action_id
            ) from None

        # 第二步：使用 isinstance 确认 question 是
        # AcceptedAskUserAction，否则抛出 QuestionActionTypeError。
        if not isinstance(question, AcceptedAskUserAction):
            raise QuestionActionTypeError(response.question_action_id)
        # 第三步：调用 validate_user_response_for_question()，
        # 复用 task_id、question_action_id 与选项规则。
        validate_user_response_for_question(response, question)

        # 第四步：调用 response.model_dump_json()得到
        # payload_json。Pydantic 负责序列化枚举和可选字段。
        payload_json = response.model_dump_json()

        # 第五步：用 sqlite3.connect(self._database_path) 打开
        # with 事务，开启 foreign_keys，然后用参数化 INSERT
        # 写入 response_id、question_action_id、task_id、
        # response_type.value 和 payload_json。
        with sqlite3.connect(self._database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            try:
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
                        payload_json,
                    ),
                )
            except sqlite3.IntegrityError:
                duplicate_id = connection.execute(
                    """
                    SELECT 1
                    FROM user_responses
                    WHERE response_id = ?
                    """,
                    (response.response_id,),
                ).fetchone()

                if duplicate_id is not None:
                    raise DuplicateUserResponseIdError(
                        response.response_id
                    ) from None

                raise DuplicateQuestionResponseError(
                    response.question_action_id
                ) from None

    def get(self, response_id: str) -> UserResponseRecord:
        """按回答编号严格恢复记录。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT question_action_id, task_id, response_type, payload_json
                FROM user_responses
                WHERE response_id = ?
                """,
                (response_id,),
            ).fetchone()

        if row is None:
            raise KeyError(response_id)

        question_action_id, task_id, response_type, payload_json = row
        try:
            response = UserResponseRecord.model_validate_json(payload_json)
        except ValidationError as exc:
            raise CorruptStoredUserResponseError(response_id, exc) from exc

        if (
            response.response_id != response_id
            or response.question_action_id != question_action_id
            or response.task_id != task_id
            or response.response_type.value != response_type
        ):
            raise CorruptStoredUserResponseError(response_id)

        return response

    def get_for_question(
        self,
        question_action_id: str,
    ) -> UserResponseRecord:
        """按原问题编号恢复它的唯一回答。"""

        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT response_id
                FROM user_responses
                WHERE question_action_id = ?
                """,
                (question_action_id,),
            ).fetchone()

        if row is None:
            raise KeyError(question_action_id)
        return self.get(row[0])

    def get_optional_for_question(
        self,
        question_action_id: str,
    ) -> UserResponseRecord | None:
        """问题尚未回答时返回 None，损坏记录仍明确失败。"""

        try:
            return self.get_for_question(question_action_id)
        except KeyError:
            return None
