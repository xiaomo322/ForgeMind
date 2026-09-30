"""把模型返回的原始 JSON 严格解析为 ForgeMind Decision。"""

from pydantic import TypeAdapter, ValidationError

from forgemind.schema.decisions import (
    AgentDecision,
    AgentDecisionParseFailure,
    ToolCallDecision,
)
from forgemind.schema.validation import (
    map_validation_error,
)


# 第二步：构造 TypeAdapter，并把 ToolCallDecision 传给它。
# TypeAdapter 让 Pydantic 能校验联合类型，而不需要再创建一层包装模型。
# 请把当前临时适配器改为针对 ToolCallDecision 的适配器。
_TOOL_CALL_DECISION_ADAPTER = TypeAdapter(ToolCallDecision)

# 第二步：构造针对 AgentDecision 的 TypeAdapter。
_AGENT_DECISION_ADAPTER = TypeAdapter(AgentDecision)


def parse_tool_call_decision(raw_response: str) -> ToolCallDecision:
    """解析并严格校验模型返回的一次 Tool 调用决策。"""

    # 第三步：调用 _TOOL_CALL_DECISION_ADAPTER.validate_json(raw_response)。
    # 它会一次完成 JSON 解析、tool_name 分派及嵌套 arguments 严格校验。
    # 直接返回结果，不捕获 ValidationError；调用方需要知道解析真实失败。
    return _TOOL_CALL_DECISION_ADAPTER.validate_json(raw_response)


def parse_agent_decision(raw_response: str) -> AgentDecision:
    """解析 Tool 调用或用户询问两类 Agent 决策。"""

    # 第三步：调用 _AGENT_DECISION_ADAPTER.validate_json(raw_response)，
    # 直接返回严格校验后的 AgentDecision。
    return _AGENT_DECISION_ADAPTER.validate_json(raw_response)


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


def parse_agent_decision_with_feedback(
    raw_response: str,
) -> AgentDecision | AgentDecisionParseFailure:
    """返回完整 AgentDecision，或返回稳定的全部校验问题。"""

    try:
        return parse_agent_decision(raw_response)
    except ValidationError as error:
        return AgentDecisionParseFailure(
            issues=tuple(map_validation_error(error))
        )
