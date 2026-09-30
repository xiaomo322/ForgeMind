"""把已解析的 Agent Decision 确定性分派到对应 Runtime 处理器。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from forgemind.schema.decisions import (
    AgentDecision,
    AgentDecisionParseFailure,
    AskUserDecision,
    EditFileToolCallDecision,
    ReadFileToolCallDecision,
    RunCommandToolCallDecision,
    RunTestsToolCallDecision,
    SearchCodeToolCallDecision,
)


DispatchResult = TypeVar("DispatchResult")


@dataclass(frozen=True, slots=True)
class AgentDecisionHandlers(Generic[DispatchResult]):
    """六种 Decision 各自必填且类型明确的 Runtime 处理器集合。"""

    ask_user: Callable[[AskUserDecision], DispatchResult]
    read_file: Callable[[ReadFileToolCallDecision], DispatchResult]
    search_code: Callable[[SearchCodeToolCallDecision], DispatchResult]
    edit_file: Callable[[EditFileToolCallDecision], DispatchResult]
    run_tests: Callable[[RunTestsToolCallDecision], DispatchResult]
    run_command: Callable[[RunCommandToolCallDecision], DispatchResult]


class UnsupportedAgentDecisionError(TypeError):
    """调用方绕过严格解析并传入未知 Decision 类型。"""

    def __init__(self, received_type: type[object]) -> None:
        self.received_type = received_type
        super().__init__(
            f"不支持的 Agent Decision 类型：{received_type.__name__}"
        )


def dispatch_agent_decision(
    decision: AgentDecision,
    *,
    handlers: AgentDecisionHandlers[DispatchResult],
) -> DispatchResult:
    """根据严格模型类型调用唯一匹配的 Runtime 处理器。"""

    # Decision 已经过 Pydantic 两层判别联合校验。这里直接按具体模型类型
    # 路由，不再解析字符串，也不猜测缺失字段或补全工具参数。
    if isinstance(decision, AskUserDecision):
        return handlers.ask_user(decision)
    if isinstance(decision, ReadFileToolCallDecision):
        return handlers.read_file(decision)
    if isinstance(decision, SearchCodeToolCallDecision):
        return handlers.search_code(decision)
    if isinstance(decision, EditFileToolCallDecision):
        return handlers.edit_file(decision)
    if isinstance(decision, RunTestsToolCallDecision):
        return handlers.run_tests(decision)
    if isinstance(decision, RunCommandToolCallDecision):
        return handlers.run_command(decision)

    # 正常类型路径不可到达；显式错误用于阻止调用方用 cast 或动态对象
    # 绕过解析边界后静默落入错误工具。
    raise UnsupportedAgentDecisionError(type(decision))


def dispatch_agent_decision_result(
    decision_result: AgentDecision | AgentDecisionParseFailure,
    *,
    handlers: AgentDecisionHandlers[DispatchResult],
) -> DispatchResult | AgentDecisionParseFailure:
    """解析失败直接返回；合法 Decision 才能进入 Runtime 处理器。"""

    # ParseFailure 不是 Action，也不是 Tool 执行失败。原样返回能让上层把
    # 校验问题反馈给 Agent，同时保证任何 Runtime 处理器都没有被调用。
    if isinstance(decision_result, AgentDecisionParseFailure):
        return decision_result

    return dispatch_agent_decision(
        decision_result,
        handlers=handlers,
    )
