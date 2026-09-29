import json

from forgemind.agent.decision_parser import (
    AgentDecisionParseFailure,
    parse_agent_decision_with_feedback,
)
from forgemind.schema.decisions import (
    AskUserDecision,
    ReadFileToolCallDecision,
)
from forgemind.schema.validation import SchemaErrorCode


def test_complete_feedback_parser_returns_tool_decision() -> None:
    result = parse_agent_decision_with_feedback(
        json.dumps(
            {
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py"},
                "reason": "读取项目代码",
            },
            ensure_ascii=False,
        )
    )

    assert type(result) is ReadFileToolCallDecision


def test_complete_feedback_parser_returns_ask_user_decision() -> None:
    result = parse_agent_decision_with_feedback(
        json.dumps(
            {
                "action_type": "ask_user",
                "reason": "缺少业务规则",
                "question": "折扣可以叠加吗？",
            },
            ensure_ascii=False,
        )
    )

    assert type(result) is AskUserDecision


def test_complete_feedback_parser_rejects_tool_fields_on_ask_user() -> None:
    result = parse_agent_decision_with_feedback(
        json.dumps(
            {
                "action_type": "ask_user",
                "reason": "缺少业务规则",
                "question": "折扣可以叠加吗？",
                "tool_name": "read_file",
            },
            ensure_ascii=False,
        )
    )

    assert type(result) is AgentDecisionParseFailure
    assert tuple(issue.code for issue in result.issues) == (
        SchemaErrorCode.UNKNOWN_FIELD,
    )
