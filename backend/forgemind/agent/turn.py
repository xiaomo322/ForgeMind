"""执行一次供应商无关的 Agent 推理，但不直接执行任何 Decision。"""

from dataclasses import dataclass
from typing import Protocol

from forgemind.agent.decision_parser import (
    AgentDecision,
    AgentDecisionParseFailure,
    parse_agent_decision_with_feedback,
)
from forgemind.context.builder import build_agent_task_context
from forgemind.context.messages import build_agent_turn_input
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.tasks import TaskStateView, TaskStatus


class TaskStateReader(Protocol):
    """Agent 单轮编排所需的最小 State 读取能力。"""

    def get_task_view(self, task_id: str) -> TaskStateView:
        """返回任务的权威当前视图。"""


class AgentModel(Protocol):
    """具体模型供应商适配器必须实现的最小调用契约。"""

    def generate(self, turn_input: AgentTurnInput) -> str:
        """根据一轮输入生成原始文本响应。"""


class AgentTurnNotRunnableError(RuntimeError):
    """任务当前状态不允许启动新的 Agent 推理。"""

    def __init__(self, task_id: str, status: TaskStatus) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(
            f"任务 {task_id!r} 当前状态为 {status.value!r}，不能启动 Agent 推理"
        )


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    """保留本轮实际输入、模型原文和严格解析结果。"""

    turn_input: AgentTurnInput
    raw_response: str
    decision_result: AgentDecision | AgentDecisionParseFailure


def run_agent_turn(
    *,
    task_id: str,
    state: TaskStateReader,
    model: AgentModel,
    max_action_count: int,
) -> AgentTurnResult:
    """读取权威 State，调用一次模型，并严格解析本轮决策。"""

    # 第一步：先读取完整任务视图并检查生命周期。等待用户或已经终止的
    # 任务不能继续调用模型，否则会产生与当前状态冲突的新决策。
    task_view = state.get_task_view(task_id)
    if task_view.current_status.status is not TaskStatus.RUNNING:
        raise AgentTurnNotRunnableError(
            task_id,
            task_view.current_status.status,
        )

    # 第二步：从权威视图选出有限上下文，再构造 system + user 消息。
    # Context Builder 会明确记录是否裁剪过 Action 历史，模型不能把片段
    # 误认为完整历史。
    context = build_agent_task_context(
        task_view,
        max_action_count=max_action_count,
    )
    turn_input = build_agent_turn_input(context)

    # 第三步：模型只返回不可信的原始字符串。网络、认证等调用异常保持原样
    # 抛出，避免把基础设施故障错误地报告成 JSON 协议错误。
    raw_response = model.generate(turn_input)

    # 第四步：严格解析负责把合法输出变成 Decision，把格式问题变成稳定的
    # ParseFailure；这一层不生成 action_id，也不写 State 或执行 Tool。
    decision_result = parse_agent_decision_with_feedback(raw_response)

    return AgentTurnResult(
        turn_input=turn_input,
        raw_response=raw_response,
        decision_result=decision_result,
    )
