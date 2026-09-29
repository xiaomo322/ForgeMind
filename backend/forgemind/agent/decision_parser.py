"""把模型返回的原始 JSON 严格解析为 ForgeMind Decision。"""

from typing import Annotated

from pydantic import Field, TypeAdapter

from forgemind.schema.decisions import (
    EditFileToolCallDecision,
    ReadFileToolCallDecision,
    RunCommandToolCallDecision,
    RunTestsToolCallDecision,
    SearchCodeToolCallDecision,
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


def parse_tool_call_decision(raw_response: str) -> ToolCallDecision:
    """解析并严格校验模型返回的一次 Tool 调用决策。"""

    # 第三步：调用 _TOOL_CALL_DECISION_ADAPTER.validate_json(raw_response)。
    # 它会一次完成 JSON 解析、tool_name 分派及嵌套 arguments 严格校验。
    # 直接返回结果，不捕获 ValidationError；调用方需要知道解析真实失败。
    return _TOOL_CALL_DECISION_ADAPTER.validate_json(raw_response)
