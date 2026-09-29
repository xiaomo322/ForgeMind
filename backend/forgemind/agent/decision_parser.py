"""把模型返回的原始 JSON 严格解析为 ForgeMind Decision。"""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from forgemind.schema.base import StrictContractModel
from forgemind.schema.decisions import (
    EditFileToolCallDecision,
    ReadFileToolCallDecision,
    RunCommandToolCallDecision,
    RunTestsToolCallDecision,
    SearchCodeToolCallDecision,
)
from forgemind.schema.validation import (
    SchemaValidationError,
    map_validation_error,
)


# 第一步：用“|”连接五种已有 Decision，形成 ToolCallDecision 联合类型；
# 再使用 Annotated 和 Field(discriminator="tool_name") 指定分派字段。
# 请把当前临时的单一类型替换为完整的带判别器联合类型。

ToolCallDecision = Annotated[
    ReadFileToolCallDecision
    | EditFileToolCallDecision
    | RunTestsToolCallDecision
    | RunCommandToolCallDecision
    | SearchCodeToolCallDecision,
    Field(discriminator="tool_name"),
]

# 第二步：构造 TypeAdapter，并把 ToolCallDecision 传给它。
# TypeAdapter 让 Pydantic 能校验联合类型，而不需要再创建一层包装模型。
# 请把当前临时适配器改为针对 ToolCallDecision 的适配器。
_TOOL_CALL_DECISION_ADAPTER = TypeAdapter(ToolCallDecision)


class AgentDecisionParseFailure(StrictContractModel):
    """模型输出无法形成合法 Decision 时的稳定反馈。"""

    outcome: Literal["invalid"] = "invalid"
    issues: tuple[SchemaValidationError, ...] = Field(min_length=1)


def parse_tool_call_decision(raw_response: str) -> ToolCallDecision:
    """解析并严格校验模型返回的一次 Tool 调用决策。"""

    # 第三步：调用 _TOOL_CALL_DECISION_ADAPTER.validate_json(raw_response)。
    # 它会一次完成 JSON 解析、tool_name 分派及嵌套 arguments 严格校验。
    # 直接返回结果，不捕获 ValidationError；调用方需要知道解析真实失败。
    return _TOOL_CALL_DECISION_ADAPTER.validate_json(raw_response)


def parse_tool_call_decision_with_feedback(
    raw_response: str,
) -> ToolCallDecision | AgentDecisionParseFailure:
    """返回合法 Decision，或返回可供 Agent 修正的稳定问题列表。"""

    # 第一步：在 try 中调用 parse_tool_call_decision(raw_response)；成功时
    # 直接返回具体的 ToolCallDecision。
    try:
        return parse_tool_call_decision(raw_response)
    # 第二步：只捕获 ValidationError，并把异常保存为 error。
    except ValidationError as error:
        # 第三步：调用 map_validation_error(error)，将返回的 list 转成
        # tuple，用它构造并返回 AgentDecisionParseFailure。不要生成
        # action_id，也不要在这里建立 Observation 或调用 Runtime。
        return AgentDecisionParseFailure(
            issues=tuple(map_validation_error(error))
        )
