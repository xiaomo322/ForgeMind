from typing import Annotated, Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.run_command import RunCommandArguments
from forgemind.schema.run_tests import RunTestsArguments
from forgemind.schema.search_code import SearchCodeArguments
from forgemind.schema.decisions import AskUserOptions


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


class AcceptedRunTestsToolAction(StrictContractModel):
    """Runtime 接受 run_tests 决策后形成的权威执行记录。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["tool_call"]
    tool_name: Literal["run_tests"]
    arguments: RunTestsArguments
    reason: str = Field(min_length=1)


class AcceptedRunCommandToolAction(StrictContractModel):
    """Runtime 接受 run_command 决策后形成的权威执行记录。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["tool_call"]
    tool_name: Literal["run_command"]
    arguments: RunCommandArguments
    reason: str = Field(min_length=1)


# 第一步：把五种 Tool Action 联合放入 Annotated，并使用
# Field(discriminator="tool_name") 建立 Tool 内部判别器。
AcceptedToolAction = Annotated[
    AcceptedReadFileToolAction
    | AcceptedSearchCodeToolAction
    | AcceptedEditFileToolAction
    | AcceptedRunTestsToolAction
    | AcceptedRunCommandToolAction,
    Field(discriminator="tool_name"),
]

class AcceptedAskUserAction(StrictContractModel):
    """Runtime 接受 ask_user 决策后形成的权威等待请求。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["ask_user"]
    reason: str = Field(min_length=1)
    question: str = Field(min_length=1)
    options: AskUserOptions | None = None


class AcceptedCompletionAction(StrictContractModel):
    """Runtime 接受完成 Decision 后保存的任务结束事实。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["complete"]
    reason: str = Field(min_length=1)
    summary: str = Field(min_length=1)


# 第二步：建立 AcceptedAction，联合 AcceptedToolAction 和
# AcceptedAskUserAction，并用 action_type 作为外层判别器。
# 当前临时类型只包含 Tool，请替换为完整的 Annotated 联合。
AcceptedAction = Annotated[
    AcceptedToolAction | AcceptedAskUserAction | AcceptedCompletionAction,
    Field(discriminator="action_type"),
]


class SequencedActionRecord(StrictContractModel):
    """State 为一个任务内的 AcceptedAction 分配的可靠登记顺序。"""

    sequence: int = Field(ge=1)
    # 第三步：把 action 类型从 AcceptedToolAction 改成 AcceptedAction。
    action: AcceptedAction
