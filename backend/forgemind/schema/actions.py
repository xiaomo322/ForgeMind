from typing import Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.read_file import ReadFileArguments


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
