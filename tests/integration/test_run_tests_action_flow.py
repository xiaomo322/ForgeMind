import pytest
from pydantic import ValidationError

from forgemind.runtime.acceptance import (
    accept_and_register_run_tests_decision,
)
from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
    AcceptedRunTestsToolAction,
)
from forgemind.schema.decisions import RunTestsToolCallDecision
from forgemind.state.action_registry import InMemoryActionRegistry


def make_run_tests_decision() -> RunTestsToolCallDecision:
    return RunTestsToolCallDecision(
        action_type="tool_call",
        tool_name="run_tests",
        arguments={"targets": ("tests",)},
        reason="验证修改后的完整测试集",
    )


def test_run_tests_decision_builds_strict_nested_arguments() -> None:
    decision = make_run_tests_decision()

    assert decision.arguments.targets == ("tests",)
    assert decision.arguments.timeout_seconds == 120


def test_run_tests_decision_rejects_agent_supplied_action_id() -> None:
    with pytest.raises(ValidationError) as captured:
        RunTestsToolCallDecision.model_validate(
            {
                "action_id": "agent-action-001",
                "action_type": "tool_call",
                "tool_name": "run_tests",
                "arguments": {"targets": ("tests",)},
                "reason": "运行测试",
            }
        )

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_runtime_accepts_and_registers_run_tests_decision() -> None:
    decision = make_run_tests_decision()
    registry = InMemoryActionRegistry()

    accepted = accept_and_register_run_tests_decision(
        decision,
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: "action-tests-001",
    )

    assert isinstance(accepted, AcceptedRunTestsToolAction)
    assert accepted.action_id == "action-tests-001"
    assert accepted.task_id == "task-001"
    assert accepted.arguments is decision.arguments
    assert registry.get(accepted.action_id) is accepted


def test_run_tests_action_id_collision_retries_without_overwriting() -> None:
    registry = InMemoryActionRegistry()
    original = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
        reason="保留原始读取",
    )
    registry.register(original)
    generated_ids = iter(["action-001", "action-002"])

    accepted = accept_and_register_run_tests_decision(
        make_run_tests_decision(),
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: next(generated_ids),
    )

    assert registry.get("action-001") is original
    assert registry.get("action-002") is accepted
