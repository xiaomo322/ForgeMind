import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from forgemind.agent.decision_parser import AgentDecisionParseFailure
from forgemind.agent.turn import (
    AgentTurnNotRunnableError,
    AgentTurnResult,
    run_agent_turn,
)
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.decisions import AskUserDecision, CompleteTaskDecision
from forgemind.schema.tasks import (
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)


@dataclass
class StaticTaskStateReader:
    """测试替身：提供已经由 State 组合完成的任务视图。"""

    task_view: TaskStateView

    def get_task_view(self, task_id: str) -> TaskStateView:
        if task_id != self.task_view.task.task_id:
            raise KeyError(task_id)
        return self.task_view


@dataclass
class RecordingAgentModel:
    """测试替身：记录真实收到的 AgentTurnInput 并返回固定响应。"""

    response: str
    received_inputs: list[AgentTurnInput] = field(default_factory=list)

    def generate(self, turn_input: AgentTurnInput) -> str:
        self.received_inputs.append(turn_input)
        return self.response


def _task_view(tmp_path: Path, status: TaskStatus) -> TaskStateView:
    task = TaskRecord(
        task_id="task-agent-turn-001",
        original_request="检查折扣计算错误",
        project_root=str(tmp_path.resolve()),
    )
    return TaskStateView(
        task=task,
        current_status=TaskStatusRecord(
            task_status_id="status-agent-turn-001",
            task_id=task.task_id,
            revision=1,
            status=status,
            reason="测试当前任务状态",
        ),
        actions=(),
    )


def test_running_agent_turn_builds_input_and_returns_valid_decision(
    tmp_path: Path,
) -> None:
    raw_response = json.dumps(
        {
            "action_type": "ask_user",
            "reason": "缺少折扣叠加规则",
            "question": "会员折扣可以和优惠券叠加吗？",
        },
        ensure_ascii=False,
    )
    model = RecordingAgentModel(raw_response)

    result = run_agent_turn(
        task_id="task-agent-turn-001",
        state=StaticTaskStateReader(
            _task_view(tmp_path, TaskStatus.RUNNING)
        ),
        model=model,
        max_action_count=5,
    )

    assert type(result) is AgentTurnResult
    assert type(result.decision_result) is AskUserDecision
    assert result.raw_response == raw_response
    assert model.received_inputs == [result.turn_input]
    assert tuple(message.role for message in result.turn_input.messages) == (
        "system",
        "user",
    )
    assert "检查折扣计算错误" in result.turn_input.messages[1].content


def test_invalid_model_output_returns_parse_failure_without_action_id(
    tmp_path: Path,
) -> None:
    result = run_agent_turn(
        task_id="task-agent-turn-001",
        state=StaticTaskStateReader(
            _task_view(tmp_path, TaskStatus.RUNNING)
        ),
        model=RecordingAgentModel("这不是 JSON"),
        max_action_count=5,
    )

    assert type(result.decision_result) is AgentDecisionParseFailure
    assert len(result.decision_result.issues) == 1
    assert not hasattr(result.decision_result, "action_id")
    assert result.attempt_count == 2


def test_invalid_model_output_is_retried_with_validation_feedback(
    tmp_path: Path,
) -> None:
    valid_response = json.dumps(
        {
            "action_type": "complete",
            "reason": "已经回答后续问题",
            "summary": "你先询问了折扣计算，随后询问此前的问题。",
        },
        ensure_ascii=False,
    )

    @dataclass
    class RepairingAgentModel:
        responses: list[str]
        received_inputs: list[AgentTurnInput] = field(default_factory=list)

        def generate(self, turn_input: AgentTurnInput) -> str:
            self.received_inputs.append(turn_input)
            return self.responses.pop(0)

    model = RepairingAgentModel(
        responses=[
            json.dumps(
                {
                    "action_type": "complete",
                    "action_type_note": "extra field",
                    "reason": "已经回答后续问题",
                    "summary": "第一次输出包含契约外字段",
                },
                ensure_ascii=False,
            ),
            valid_response,
        ]
    )

    result = run_agent_turn(
        task_id="task-agent-turn-001",
        state=StaticTaskStateReader(
            _task_view(tmp_path, TaskStatus.RUNNING)
        ),
        model=model,
        max_action_count=5,
    )

    assert type(result.decision_result) is CompleteTaskDecision
    assert result.raw_response == valid_response
    assert result.attempt_count == 2
    assert len(model.received_inputs) == 2
    assert "UNKNOWN_FIELD" in model.received_inputs[1].messages[1].content
    assert "只返回修正后的 JSON 对象" in model.received_inputs[1].messages[1].content


def test_non_running_task_is_rejected_before_model_call(
    tmp_path: Path,
) -> None:
    model = RecordingAgentModel("不应该调用")

    with pytest.raises(AgentTurnNotRunnableError) as captured:
        run_agent_turn(
            task_id="task-agent-turn-001",
            state=StaticTaskStateReader(
                _task_view(tmp_path, TaskStatus.WAITING_USER)
            ),
            model=model,
            max_action_count=5,
        )

    assert captured.value.task_id == "task-agent-turn-001"
    assert captured.value.status is TaskStatus.WAITING_USER
    assert model.received_inputs == []


def test_model_client_failure_remains_a_real_call_failure(
    tmp_path: Path,
) -> None:
    expected_error = ConnectionError("模型服务不可用")

    class FailingAgentModel:
        def generate(self, turn_input: AgentTurnInput) -> str:
            raise expected_error

    with pytest.raises(ConnectionError) as captured:
        run_agent_turn(
            task_id="task-agent-turn-001",
            state=StaticTaskStateReader(
                _task_view(tmp_path, TaskStatus.RUNNING)
            ),
            model=FailingAgentModel(),
            max_action_count=5,
        )

    assert captured.value is expected_error
