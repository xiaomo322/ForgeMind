import pytest
from pydantic import ValidationError

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.decisions import ReadFileToolCallDecision


def test_runtime_can_build_accepted_action_from_validated_decision() -> None:
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )

    accepted = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type=decision.action_type,
        tool_name=decision.tool_name,
        arguments=decision.arguments,
        reason=decision.reason,
    )

    assert accepted.action_id == "action-001"
    assert accepted.task_id == "task-001"
    assert accepted.arguments.model_dump() == {
        "path": "src/app.py",
        "start_line": 1,
        "max_lines": 200,
        "expected_version": None,
    }


@pytest.mark.parametrize(
    "invalid_field",
    [
        {"action_id": ""},
        {"task_id": ""},
        {"action_type": "ask_user"},
        {"tool_name": "search_code"},
        {"reason": ""},
    ],
)
def test_accepted_read_file_action_rejects_invalid_authoritative_fields(
    invalid_field: dict[str, str],
) -> None:
    payload = {
        "action_id": "action-001",
        "task_id": "task-001",
        "action_type": "tool_call",
        "tool_name": "read_file",
        "arguments": {"path": "src/app.py"},
        "reason": "读取价格计算逻辑",
    }
    payload.update(invalid_field)

    with pytest.raises(ValidationError):
        AcceptedReadFileToolAction.model_validate(payload)


def test_accepted_action_rejects_changes_through_nested_arguments() -> None:
    accepted = AcceptedReadFileToolAction.model_validate(
        {
            "action_id": "action-001",
            "task_id": "task-001",
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )

    with pytest.raises(ValidationError) as captured:
        accepted.arguments.max_lines = 500

    assert captured.value.errors()[0]["type"] == "frozen_instance"
