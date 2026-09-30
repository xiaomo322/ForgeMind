"""校验用户回答是否属于它声称回答的 AskUserAction。"""

from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord, UserResponseType


class UserResponseQuestionMismatchError(ValueError):
    """回答的任务或问题编号与原询问不一致。"""

    def __init__(self, mismatched_fields: tuple[str, ...]) -> None:
        self.mismatched_fields = mismatched_fields
        super().__init__(f"用户回答与原问题不匹配: {mismatched_fields}")


class InvalidUserResponseSelectionError(ValueError):
    """用户回答与原问题的选项约束不一致。"""


def validate_user_response_for_question(
    response: UserResponseRecord,
    question: AcceptedAskUserAction,
) -> UserResponseRecord:
    """把回答与原问题交叉校验，成功时返回原不可变记录。"""

    # 第一步：建立空列表 mismatched_fields。
    mismatched_fields: list[str] = []
    # response.task_id 不等于 question.task_id 时追加 "task_id"；
    # response.question_action_id 不等于 question.action_id 时
    # 追加 "question_action_id"。
    if response.task_id != question.task_id:
        mismatched_fields.append("task_id")
    if response.question_action_id != question.action_id:
        mismatched_fields.append("question_action_id")
    # 第二步：若 mismatched_fields 非空，把它转为 tuple，
    # 并抛出 UserResponseQuestionMismatchError。先校验标识，防止
    # Runtime 使用错误问题的 options 解释这条回答。
    if mismatched_fields:
        raise UserResponseQuestionMismatchError(tuple(mismatched_fields))

    # 第三步：若 response_type 是 CANCEL，直接返回 response。
    # 取消不是对选项的回答，不需要匹配 question.options。
    if response.response_type is UserResponseType.CANCEL:
        return response

    # 第四步：处理自由文本问题。
    # question.options is None 时，response.selected_option 也必须是
    # None；否则抛出 InvalidUserResponseSelectionError。
    if question.options is None:
        if response.selected_option is not None:
            raise InvalidUserResponseSelectionError("自由文本问题不能携带 selected_option")
    # 第五步：处理单选问题。question.options 存在时：
    # - selected_option 为 None，说明没有得到可执行的选择，抛错；
    # - selected_option not in question.options，说明选了原问题
    #   不存在的值，抛错。
    else:
        if response.selected_option is None:
            raise InvalidUserResponseSelectionError("单选问题必须提供 selected_option")

        if response.selected_option not in question.options:
            raise InvalidUserResponseSelectionError("selected_option 不属于原问题选项")
    # 第六步：全部校验通过后返回 response。它是 frozen
    # Pydantic 模型，Runtime 只确认它，不应原地改写用户记录。
    return response
