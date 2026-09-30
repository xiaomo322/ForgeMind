"""用户回答的单进程内存注册表。"""

from forgemind.runtime.user_responses import validate_user_response_for_question
from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord
from forgemind.state.action_registry import InMemoryActionRegistry


class UnknownQuestionActionIdError(ValueError):
    """回答引用的问题 Action 不存在。"""


class QuestionActionTypeError(ValueError):
    """回答引用的 Action 不是 ask_user。"""


class DuplicateUserResponseIdError(ValueError):
    """response_id 已经指向一条用户回答。"""


class DuplicateQuestionResponseError(ValueError):
    """同一问题已经存在用户回答。"""


class InMemoryUserResponseRegistry:
    """V0.1 单进程用户回答注册表。"""

    def __init__(self, actions: InMemoryActionRegistry) -> None:
        self._actions = actions
        self._by_id: dict[str, UserResponseRecord] = {}
        self._by_question_action_id: dict[str, UserResponseRecord] = {}

    def record(self, response: UserResponseRecord) -> None:
        """校验原问题后追加回答，不覆盖任何已有事实。"""

        # 第一步：用 response.question_action_id 调用
        # self._actions.get()。若它抛出 KeyError，转换为
        # UnknownQuestionActionIdError，并使用 from None 隐去底层
        # dict 的 KeyError 上下文。
        try:
            question = self._actions.get(response.question_action_id)
        except KeyError:
            raise UnknownQuestionActionIdError(
                response.question_action_id
            ) from None
        # 第二步：使用 isinstance(question, AcceptedAskUserAction)
        # 检查 Action 类型。若不是，抛出 QuestionActionTypeError。
        # 只有 ask_user Action 可以被 UserResponseRecord 回答。
        if not isinstance(question, AcceptedAskUserAction):
            raise QuestionActionTypeError(response.question_action_id)
        # 第三步：调用 validate_user_response_for_question(response,
        # question)。这里复用 Runtime 上一节的身份和选项规则，
        # 不在 State 里复制第二份规则。
        validate_user_response_for_question(response, question)
        # 第四步：若 response.response_id 已在 self._by_id，
        # 抛出 DuplicateUserResponseIdError。
        if response.response_id in self._by_id:
            raise DuplicateUserResponseIdError(response.response_id)
        # 第五步：若 response.question_action_id 已在
        # self._by_question_action_id，抛出 DuplicateQuestionResponseError。
        # 这防止第二条相反回答覆盖第一条用户事实。
        if response.question_action_id in self._by_question_action_id:
            raise DuplicateQuestionResponseError(
                response.question_action_id
            )
        # 第六步：所有检查通过后，分别按 response_id 和
        # question_action_id 把同一个 response 对象写入两个索引。
        self._by_id[response.response_id] = response
        self._by_question_action_id[response.question_action_id] = response

    def get(self, response_id: str) -> UserResponseRecord:
        """按回答编号取得不可变记录。"""

        return self._by_id[response_id]

    def get_for_question(self, question_action_id: str) -> UserResponseRecord:
        """取得一个 AskUserAction 对应的唯一回答。"""

        return self._by_question_action_id[question_action_id]
