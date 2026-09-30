import json
from dataclasses import dataclass, field
from pathlib import Path

from forgemind.agent.loop import AgentLoopStepResult, run_agent_loop_step
from forgemind.runtime.ask_user import (
    AskUserWaitingResult,
    accept_ask_user_and_wait,
)
from forgemind.runtime.decision_dispatch import AgentDecisionHandlers
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.decisions import AgentDecisionParseFailure
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


@dataclass
class RecordingAgentModel:
    """记录本轮真实输入，并返回测试指定的模型原文。"""

    response: str
    received_inputs: list[AgentTurnInput] = field(default_factory=list)

    def generate(self, turn_input: AgentTurnInput) -> str:
        self.received_inputs.append(turn_input)
        return self.response


def _running_state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "loop-state.db")
    task = TaskRecord(
        task_id="task-loop-001",
        original_request="修复会员折扣计算错误",
        project_root=str(tmp_path.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-loop-running-001",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state


def _unexpected_handler(_: object) -> AskUserWaitingResult:
    raise AssertionError("不应调用其他 Decision 处理器")


def _ask_user_handlers(
    state: SQLiteForgeMindState,
) -> AgentDecisionHandlers[AskUserWaitingResult]:
    return AgentDecisionHandlers(
        ask_user=lambda decision: accept_ask_user_and_wait(
            decision,
            task_id="task-loop-001",
            state=state,
            next_action_id=lambda: "action-loop-ask-001",
            next_task_status_id=lambda: "status-loop-waiting-002",
        ),
        read_file=_unexpected_handler,
        search_code=_unexpected_handler,
        edit_file=_unexpected_handler,
        run_tests=_unexpected_handler,
        run_command=_unexpected_handler,
    )


def test_loop_step_dispatches_ask_user_and_persists_waiting_state(
    tmp_path: Path,
) -> None:
    state = _running_state(tmp_path)
    model = RecordingAgentModel(
        json.dumps(
            {
                "action_type": "ask_user",
                "reason": "缺少折扣叠加规则",
                "question": "会员折扣可以与优惠券叠加吗？",
                "options": ["可以", "不可以"],
            },
            ensure_ascii=False,
        )
    )

    result = run_agent_loop_step(
        task_id="task-loop-001",
        state=state,
        model=model,
        handlers=_ask_user_handlers(state),
        max_action_count=5,
    )

    assert type(result) is AgentLoopStepResult
    assert type(result.dispatch_result) is AskUserWaitingResult
    assert model.received_inputs == [result.turn_result.turn_input]
    assert "修复会员折扣计算错误" in (
        result.turn_result.turn_input.messages[1].content
    )

    restored = SQLiteForgeMindState.open(
        tmp_path / "loop-state.db"
    ).get_task_view("task-loop-001")
    assert restored.current_status.status is TaskStatus.WAITING_USER
    assert restored.current_status.revision == 2
    assert len(restored.actions) == 1
    assert restored.actions[0].action.action_id == "action-loop-ask-001"
    assert restored.actions[0].action.question == (
        "会员折扣可以与优惠券叠加吗？"
    )


def test_loop_step_parse_failure_leaves_authoritative_state_unchanged(
    tmp_path: Path,
) -> None:
    state = _running_state(tmp_path)

    result = run_agent_loop_step(
        task_id="task-loop-001",
        state=state,
        model=RecordingAgentModel("这不是 JSON"),
        handlers=_ask_user_handlers(state),
        max_action_count=5,
    )

    assert type(result.dispatch_result) is AgentDecisionParseFailure
    assert result.dispatch_result is result.turn_result.decision_result

    restored = SQLiteForgeMindState.open(
        tmp_path / "loop-state.db"
    ).get_task_view("task-loop-001")
    assert restored.current_status.status is TaskStatus.RUNNING
    assert restored.current_status.revision == 1
    assert restored.actions == ()
