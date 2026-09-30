"""组合一次 Agent 推理与一次确定性 Runtime 分派。"""

from dataclasses import dataclass
from typing import Generic, TypeVar

from forgemind.agent.turn import (
    AgentModel,
    AgentTurnResult,
    TaskStateReader,
    run_agent_turn,
)
from forgemind.runtime.decision_dispatch import (
    AgentDecisionHandlers,
    dispatch_agent_decision_result,
)
from forgemind.schema.decisions import AgentDecisionParseFailure


LoopDispatchResult = TypeVar("LoopDispatchResult")


@dataclass(frozen=True, slots=True)
class AgentLoopStepResult(Generic[LoopDispatchResult]):
    """同时保留本轮推理证据和 Runtime 分派结果。"""

    turn_result: AgentTurnResult
    dispatch_result: LoopDispatchResult | AgentDecisionParseFailure


def run_agent_loop_step(
    *,
    task_id: str,
    state: TaskStateReader,
    model: AgentModel,
    handlers: AgentDecisionHandlers[LoopDispatchResult],
    max_action_count: int,
) -> AgentLoopStepResult[LoopDispatchResult]:
    """运行一次 State → Agent → Decision → Runtime 的单轮步骤。"""

    # 第一步：读取当前权威 State、构造有限上下文、调用一次模型并严格
    # 解析。模型调用期间不持有数据库事务或写锁。
    turn_result = run_agent_turn(
        task_id=task_id,
        state=state,
        model=model,
        max_action_count=max_action_count,
    )

    # 第二步：ParseFailure 会在 Dispatcher 中原样短路；只有合法 Decision
    # 才调用一个具体 Runtime handler。handler 必须在产生副作用前重新校验
    # 当前 State，不能假设模型思考前读取的快照仍然有效。
    dispatch_result = dispatch_agent_decision_result(
        turn_result.decision_result,
        handlers=handlers,
    )

    # 第三步：同时返回推理证据与处理结果，使调用方能区分模型调用、协议
    # 解析和 Runtime 执行三个阶段，而不是只看到一个模糊的成功或失败。
    return AgentLoopStepResult(
        turn_result=turn_result,
        dispatch_result=dispatch_result,
    )
