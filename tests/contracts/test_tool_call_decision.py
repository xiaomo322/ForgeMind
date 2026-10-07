import pytest
from pydantic import ValidationError

from forgemind.schema.decisions import ReadFileToolCallDecision


def test_read_file_tool_call_normalizes_nested_arguments() -> None:
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )

    assert decision.action_type == "tool_call"
    assert decision.tool_name == "read_file"
    assert decision.arguments.model_dump() == {
        "path": "src/app.py",
        "start_line": 1,
        "max_lines": 200,
        "expected_version": None,
    }


@pytest.mark.parametrize(
    "invalid_field",
    [
        {"action_type": "ask_user"},
        {"tool_name": "search_code"},
        {"reason": ""},
    ],
)
def test_read_file_tool_call_rejects_invalid_routing_fields(
    invalid_field: dict[str, str],
) -> None:
    payload = {
        "action_type": "tool_call",
        "tool_name": "read_file",
        "arguments": {"path": "src/app.py"},
        "reason": "读取价格计算逻辑",
    }
    payload.update(invalid_field)

    with pytest.raises(ValidationError):
        ReadFileToolCallDecision.model_validate(payload)
