import json

import pytest
from pydantic import ValidationError

from forgemind.agent.decision_parser import parse_tool_call_decision
from forgemind.schema.decisions import (
    EditFileToolCallDecision,
    ReadFileToolCallDecision,
    RunCommandToolCallDecision,
    RunTestsToolCallDecision,
    SearchCodeToolCallDecision,
)


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        (
            {
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py"},
                "reason": "读取价格计算逻辑",
            },
            ReadFileToolCallDecision,
        ),
        (
            {
                "action_type": "tool_call",
                "tool_name": "search_code",
                "arguments": {"query": "discount"},
                "reason": "定位折扣相关代码",
            },
            SearchCodeToolCallDecision,
        ),
        (
            {
                "action_type": "tool_call",
                "tool_name": "edit_file",
                "arguments": {
                    "path": "src/app.py",
                    "old_text": "price = 100",
                    "new_text": "price = 90",
                    "expected_version": "sha256:v1",
                },
                "reason": "修正价格计算",
            },
            EditFileToolCallDecision,
        ),
        (
            {
                "action_type": "tool_call",
                "tool_name": "run_tests",
                "arguments": {"targets": ["tests/test_app.py"]},
                "reason": "验证修改结果",
            },
            RunTestsToolCallDecision,
        ),
        (
            {
                "action_type": "tool_call",
                "tool_name": "run_command",
                "arguments": {
                    "program": "python",
                    "args": ["-m", "forgemind"],
                    "working_directory": ".",
                },
                "reason": "验证真实程序入口",
            },
            RunCommandToolCallDecision,
        ),
    ],
)
def test_parser_dispatches_each_tool_to_its_existing_decision_model(
    payload: dict[str, object],
    expected_type: type,
) -> None:
    decision = parse_tool_call_decision(
        json.dumps(payload, ensure_ascii=False)
    )

    assert type(decision) is expected_type
    assert decision.tool_name == payload["tool_name"]


@pytest.mark.parametrize(
    "raw_response",
    [
        "不是 JSON",
        json.dumps(
            {
                "action_type": "tool_call",
                "tool_name": "delete_file",
                "arguments": {"path": "src/app.py"},
                "reason": "删除文件",
            }
        ),
        json.dumps(
            {
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py", "max_lines": "200"},
                "reason": "读取文件",
            }
        ),
        json.dumps(
            {
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py"},
                "reason": "读取文件",
                "action_id": "agent-must-not-create-this",
            }
        ),
    ],
)
def test_parser_rejects_untrusted_invalid_model_output(
    raw_response: str,
) -> None:
    with pytest.raises(ValidationError):
        parse_tool_call_decision(raw_response)
