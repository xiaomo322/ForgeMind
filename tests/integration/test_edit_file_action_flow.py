import pytest
from pydantic import ValidationError

from forgemind.runtime.acceptance import (
    accept_and_register_edit_file_decision,
)
from forgemind.schema.actions import (
    AcceptedEditFileToolAction,
    AcceptedSearchCodeToolAction,
)
from forgemind.schema.decisions import EditFileToolCallDecision
from forgemind.state.action_registry import InMemoryActionRegistry


def make_edit_decision() -> EditFileToolCallDecision:
    return EditFileToolCallDecision(
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "src/app.py",
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": "sha256:v1",
        },
        reason="修正折扣逻辑",
    )


def test_edit_decision_builds_strict_nested_arguments() -> None:
    decision = make_edit_decision()

    assert decision.arguments.path == "src/app.py"
    assert decision.arguments.expected_version == "sha256:v1"


def test_edit_decision_rejects_agent_supplied_action_id() -> None:
    with pytest.raises(ValidationError) as captured:
        EditFileToolCallDecision.model_validate(
            {
                "action_id": "agent-action-001",
                "action_type": "tool_call",
                "tool_name": "edit_file",
                "arguments": {
                    "path": "src/app.py",
                    "old_text": "old",
                    "new_text": "new",
                    "expected_version": "sha256:v1",
                },
                "reason": "修改文件",
            }
        )

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_runtime_accepts_and_registers_edit_decision() -> None:
    decision = make_edit_decision()
    registry = InMemoryActionRegistry()

    accepted = accept_and_register_edit_file_decision(
        decision,
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: "action-edit-001",
    )

    assert isinstance(accepted, AcceptedEditFileToolAction)
    assert accepted.action_id == "action-edit-001"
    assert accepted.task_id == "task-001"
    assert accepted.arguments is decision.arguments
    assert registry.get("action-edit-001") is accepted


def test_edit_action_id_collision_retries_without_overwriting() -> None:
    registry = InMemoryActionRegistry()
    original = AcceptedSearchCodeToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="search_code",
        arguments={"query": "discount"},
        reason="保留原始搜索",
    )
    registry.register(original)
    generated_ids = iter(["action-001", "action-002"])

    accepted = accept_and_register_edit_file_decision(
        make_edit_decision(),
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: next(generated_ids),
    )

    assert registry.get("action-001") is original
    assert registry.get("action-002") is accepted
