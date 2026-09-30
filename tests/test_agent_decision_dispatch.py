from collections.abc import Callable
from typing import cast

import pytest

from forgemind.agent.decision_parser import (
    parse_agent_decision_with_feedback,
)
from forgemind.runtime.decision_dispatch import (
    AgentDecisionHandlers,
    UnsupportedAgentDecisionError,
    dispatch_agent_decision,
    dispatch_agent_decision_result,
)
from forgemind.schema.decisions import (
    AgentDecision,
    AgentDecisionParseFailure,
    AskUserDecision,
    EditFileToolCallDecision,
    ReadFileToolCallDecision,
    RunCommandToolCallDecision,
    RunTestsToolCallDecision,
    SearchCodeToolCallDecision,
)


DECISION_CASES: tuple[tuple[AgentDecision, str], ...] = (
    (
        AskUserDecision(
            action_type="ask_user",
            reason="缺少折扣规则",
            question="折扣可以叠加吗？",
        ),
        "ask_user",
    ),
    (
        ReadFileToolCallDecision(
            action_type="tool_call",
            tool_name="read_file",
            arguments={"path": "src/pricing.py"},
            reason="读取价格代码",
        ),
        "read_file",
    ),
    (
        SearchCodeToolCallDecision(
            action_type="tool_call",
            tool_name="search_code",
            arguments={"query": "discount"},
            reason="查找折扣计算位置",
        ),
        "search_code",
    ),
    (
        EditFileToolCallDecision(
            action_type="tool_call",
            tool_name="edit_file",
            arguments={
                "path": "src/pricing.py",
                "old_text": "discount = 1",
                "new_text": "discount = 2",
                "expected_version": "version-001",
            },
            reason="修正折扣值",
        ),
        "edit_file",
    ),
    (
        RunTestsToolCallDecision(
            action_type="tool_call",
            tool_name="run_tests",
            arguments={"targets": ("tests/test_pricing.py",)},
            reason="验证折扣修改",
        ),
        "run_tests",
    ),
    (
        RunCommandToolCallDecision(
            action_type="tool_call",
            tool_name="run_command",
            arguments={
                "program": "python",
                "args": ("-m", "compileall", "src"),
                "working_directory": ".",
            },
            reason="检查 Python 语法",
        ),
        "run_command",
    ),
)


def _recording_handlers(
    calls: list[tuple[str, object]],
) -> AgentDecisionHandlers[str]:
    def record(route: str) -> Callable[[object], str]:
        def handle(decision: object) -> str:
            calls.append((route, decision))
            return route

        return handle

    return AgentDecisionHandlers(
        ask_user=record("ask_user"),
        read_file=record("read_file"),
        search_code=record("search_code"),
        edit_file=record("edit_file"),
        run_tests=record("run_tests"),
        run_command=record("run_command"),
    )


@pytest.mark.parametrize(("decision", "expected_route"), DECISION_CASES)
def test_dispatch_calls_only_matching_typed_handler(
    decision: AgentDecision,
    expected_route: str,
) -> None:
    calls: list[tuple[str, object]] = []

    result = dispatch_agent_decision(
        decision,
        handlers=_recording_handlers(calls),
    )

    assert result == expected_route
    assert calls == [(expected_route, decision)]


def test_parse_failure_returns_without_calling_any_handler() -> None:
    parse_result = parse_agent_decision_with_feedback("不是 JSON")
    assert type(parse_result) is AgentDecisionParseFailure
    calls: list[tuple[str, object]] = []

    result = dispatch_agent_decision_result(
        parse_result,
        handlers=_recording_handlers(calls),
    )

    assert result is parse_result
    assert calls == []


def test_dispatch_rejects_unknown_decision_type() -> None:
    calls: list[tuple[str, object]] = []

    with pytest.raises(UnsupportedAgentDecisionError) as captured:
        dispatch_agent_decision(
            cast(AgentDecision, object()),
            handlers=_recording_handlers(calls),
        )

    assert captured.value.received_type is object
    assert calls == []
