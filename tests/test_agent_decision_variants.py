import json

import pytest
from pydantic import ValidationError

from forgemind.agent.decision_parser import parse_agent_decision
from forgemind.schema.decisions import (
    AskUserDecision,
    ReadFileToolCallDecision,
)


def test_agent_parser_routes_tool_call_through_nested_tool_discriminator() -> None:
    decision = parse_agent_decision(
        json.dumps(
            {
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py"},
                "reason": "读取价格计算逻辑",
            },
            ensure_ascii=False,
        )
    )

    assert type(decision) is ReadFileToolCallDecision


def test_agent_parser_routes_ask_user_without_tool_fields() -> None:
    decision = parse_agent_decision(
        json.dumps(
            {
                "action_type": "ask_user",
                "reason": "项目中没有折扣叠加规则",
                "question": "会员折扣和优惠券可以同时使用吗？",
                "options": ["可以", "不可以"],
            },
            ensure_ascii=False,
        )
    )

    assert type(decision) is AskUserDecision
    assert decision.options == ("可以", "不可以")


def test_agent_parser_rejects_unknown_action_type() -> None:
    with pytest.raises(ValidationError):
        parse_agent_decision(
            json.dumps(
                {
                    "action_type": "silently_change_state",
                    "reason": "绕过 Runtime",
                }
            )
        )
