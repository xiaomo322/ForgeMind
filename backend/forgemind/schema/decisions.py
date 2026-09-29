from typing import Annotated, Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.run_command import RunCommandArguments
from forgemind.schema.run_tests import RunTestsArguments
from forgemind.schema.search_code import SearchCodeArguments


NonEmptyUserOption = Annotated[str, Field(min_length=1)]
AskUserOptions = Annotated[
    tuple[NonEmptyUserOption, ...],
    Field(min_length=1),
]


class ReadFileToolCallDecision(StrictContractModel):
    """Agent 请求调用 read_file 时必须产生的完整决策结构。"""

    # 这两个 Literal 是路由标签。Runtime 只接受精确值，不能猜测
    # "read"、"file_read" 等近似名称实际代表哪个动作或工具。
    action_type: Literal["tool_call"]
    tool_name: Literal["read_file"]

    # 嵌套模型会继续执行 ReadFileArguments 的严格类型、未知字段、
    # 缺省值和字段范围校验。
    arguments: ReadFileArguments

    # reason 供审查和上下文使用，但不能替代 arguments 或执行授权。
    reason: str = Field(min_length=1)


class SearchCodeToolCallDecision(StrictContractModel):
    """Agent 请求调用 search_code 时必须产生的完整决策结构。"""

    action_type: Literal["tool_call"]
    tool_name: Literal["search_code"]
    arguments: SearchCodeArguments
    reason: str = Field(min_length=1)


class EditFileToolCallDecision(StrictContractModel):
    """Agent 请求调用 edit_file 时必须产生的完整决策结构。"""

    action_type: Literal["tool_call"]
    tool_name: Literal["edit_file"]
    arguments: EditFileArguments
    reason: str = Field(min_length=1)


class RunTestsToolCallDecision(StrictContractModel):
    """Agent 请求调用 run_tests 时必须产生的完整决策结构。"""

    action_type: Literal["tool_call"]
    tool_name: Literal["run_tests"]
    arguments: RunTestsArguments
    reason: str = Field(min_length=1)


class RunCommandToolCallDecision(StrictContractModel):
    """Agent 请求调用 run_command 时必须产生的完整决策结构。"""

    action_type: Literal["tool_call"]
    tool_name: Literal["run_command"]
    arguments: RunCommandArguments
    reason: str = Field(min_length=1)


class AskUserDecision(StrictContractModel):
    """Agent 缺少必须由用户提供的信息时提出的明确问题。"""

    # 第一步：声明 action_type，只允许字面值 "ask_user"。
    action_type: Literal["ask_user"]
    # 第二步：声明非空 reason，说明为什么现有证据不足以继续决策。
    reason: str = Field(min_length=1)
    # 第三步：声明非空 question，它是实际展示给用户的问题。
    question: str = Field(min_length=1)

    # 第四步：声明 options，类型为 AskUserOptions | None，默认值为 None。
    # 有明确选项时传不可变元组；自由文本问题不需要伪造选项。
    options: AskUserOptions | None = None
