from typing import Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.search_code import SearchCodeArguments


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
