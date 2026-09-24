from typing import Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.search_code import SearchCodeArguments


class AcceptedReadFileToolAction(StrictContractModel):
    """Runtime 接受 read_file 决策后形成的权威执行记录。"""

    # 两个标识均由 Runtime 提供，Agent Decision 中不存在这些字段；
    # 非空约束只能保证形状，真正的唯一性由 Runtime 的 ID 分配器负责。
    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)

    # AcceptedAction 必须保留 Decision 的确定性路由标签，不能在接受后
    # 被改成另一种动作或工具。
    action_type: Literal["tool_call"]
    tool_name: Literal["read_file"]
    arguments: ReadFileArguments
    reason: str = Field(min_length=1)


class AcceptedSearchCodeToolAction(StrictContractModel):
    """Runtime 接受 search_code 决策后形成的权威执行记录。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["tool_call"]
    tool_name: Literal["search_code"]
    arguments: SearchCodeArguments
    reason: str = Field(min_length=1)


class AcceptedEditFileToolAction(StrictContractModel):
    """Runtime 接受 edit_file 决策后形成的权威执行记录。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["tool_call"]
    tool_name: Literal["edit_file"]
    arguments: EditFileArguments
    reason: str = Field(min_length=1)


AcceptedToolAction = (
    AcceptedReadFileToolAction
    | AcceptedSearchCodeToolAction
    | AcceptedEditFileToolAction
)
