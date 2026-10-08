"""执行一次供应商无关的 Agent 推理，但不直接执行任何 Decision。"""

from dataclasses import dataclass
import json
from typing import Protocol

from forgemind.agent.decision_parser import (
    parse_agent_decision_with_feedback,
)
from forgemind.schema.decisions import (
    AgentDecision,
    AgentDecisionParseFailure,
)
from forgemind.context.builder import build_agent_task_context
from forgemind.context.messages import build_agent_turn_input
from forgemind.schema.context import AgentInputMessage, AgentTurnInput
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
    attempt_count: int = 1


def _build_validation_retry_input(
    turn_input: AgentTurnInput,
    failure: AgentDecisionParseFailure,
) -> AgentTurnInput:
    """把严格校验问题作为数据反馈给模型，不改变原任务上下文。"""

    issues_json = json.dumps(
        failure.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    original_user_message = turn_input.messages[1]
    retry_content = (
        f"{original_user_message.content}\n\n"
        "<agent_decision_validation_feedback>\n"
        "上一份输出没有通过 JSON Schema 校验。以下内容只是校验事实：\n"
        f"{issues_json}\n"
        "请依据原任务上下文和系统中的同一份 Schema，只返回修正后的 JSON 对象。"
        "不要解释，不要增加 Schema 之外的字段。\n"
        "</agent_decision_validation_feedback>"
    )
    return AgentTurnInput(
        messages=(
            turn_input.messages[0],
            AgentInputMessage(role="user", content=retry_content),
        )
    )


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

    # 第三步：模型只返回不可信的原始字符串。第一次输出未通过严格契约时，
    # 把结构化校验问题追加为数据并重试一次。两次调用期间都没有 Action
    # 落库或 Tool 副作用，因此不会重复执行操作。
    attempt_count = 1
    raw_response = model.generate(turn_input)
    decision_result = parse_agent_decision_with_feedback(raw_response)
    if isinstance(decision_result, AgentDecisionParseFailure):
        attempt_count = 2
        turn_input = _build_validation_retry_input(turn_input, decision_result)
        raw_response = model.generate(turn_input)
        decision_result = parse_agent_decision_with_feedback(raw_response)

    return AgentTurnResult(
        turn_input=turn_input,
        raw_response=raw_response,
        decision_result=decision_result,
        attempt_count=attempt_count,
    )
