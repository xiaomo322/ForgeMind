"""用户与 Agent 交互过程中的不可变记录。"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from forgemind.schema.base import StrictContractModel


class UserResponseType(StrEnum):
    """用户对 AskUserAction 的两种互斥回应。"""

    ANSWER = "answer"
    CANCEL = "cancel"


class UserResponseRecord(StrictContractModel):
    """保留用户原话及其所回答问题的不可变记录。"""

    # 第一步：声明 response_id、task_id 和 question_action_id。
    # 它们都是非空字符串；question_action_id 指向原始
    # AcceptedAskUserAction，不能用 response_id 代替。
    response_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    question_action_id: str = Field(min_length=1)
    # 第二步：声明 response_type 为 UserResponseType。
    # Runtime 使用稳定枚举分支，不解析自然语言猜测是回答还是取消。
    response_type: UserResponseType
    # 第三步：声明 raw_response 为非空字符串。
    # 它保留用户原话，不能被归一化的枚举或选项覆盖。
    raw_response: str = Field(min_length=1)
    # 第四步：声明两个可选非空字符串，默认均为 None。
    # selected_option 保存结构化单选结果；cancellation_reason
    # 保存可选的归一化取消原因。
    selected_option: str | None = Field(default=None, min_length=1)
    cancellation_reason: str | None = Field(default=None, min_length=1)
    # 第五步：添加 mode="after" 的 model_validator。
    # after 校验器在单字段类型/长度校验通过后运行，因此可以安全读取
    # self.response_type、self.selected_option 和 self.cancellation_reason。
    # - answer 携带 cancellation_reason 时抛出 ValueError；
    # - cancel 携带 selected_option 时抛出 ValueError；
    # - 其他情况返回 self。
    @model_validator(mode="after")
    def validate_response_details(self) -> Self:
        if (
            self.response_type is UserResponseType.ANSWER
            and self.cancellation_reason is not None
        ):
            raise ValueError("answer 不能携带 cancellation_reason")

        if (
            self.response_type is UserResponseType.CANCEL
            and self.selected_option is not None
        ):
            raise ValueError("cancel 不能携带 selected_option")
        return self
