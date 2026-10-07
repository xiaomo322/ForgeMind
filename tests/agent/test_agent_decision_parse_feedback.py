import json

from forgemind.agent.decision_parser import (
    AgentDecisionParseFailure,
    parse_tool_call_decision_with_feedback,
)
from forgemind.schema.decisions import ReadFileToolCallDecision
from forgemind.schema.validation import SchemaErrorCode


def test_feedback_parser_returns_valid_decision_unchanged() -> None:
    raw_response = json.dumps(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        },
        ensure_ascii=False,
    )

    result = parse_tool_call_decision_with_feedback(raw_response)

    assert type(result) is ReadFileToolCallDecision
    assert result.arguments.path == "src/app.py"


def test_feedback_parser_returns_all_stable_validation_issues() -> None:
    raw_response = json.dumps(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {
                "path": "src/app.py",
                "max_lines": "200",
                "recursive": True,
            },
            "reason": "读取文件",
        }
    )

    result = parse_tool_call_decision_with_feedback(raw_response)
    print(result)
    print("___"*30)
    assert type(result) is AgentDecisionParseFailure
    assert result.outcome == "invalid"
    assert tuple(issue.code for issue in result.issues) == (
        SchemaErrorCode.INVALID_TYPE,
        SchemaErrorCode.UNKNOWN_FIELD,
    )
    assert not hasattr(result, "action_id")


def test_feedback_parser_represents_malformed_json_without_execution_state() -> None:
    result = parse_tool_call_decision_with_feedback("不是 JSON")

    assert type(result) is AgentDecisionParseFailure
    assert len(result.issues) == 1
    assert result.issues[0].code is SchemaErrorCode.INVALID_VALUE
    assert not hasattr(result, "status")
    assert not hasattr(result, "action_id")
