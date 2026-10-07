import pytest
from pydantic import ValidationError

from forgemind.runtime.acceptance import (
    accept_and_register_search_code_decision,
)
from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
    AcceptedSearchCodeToolAction,
)
from forgemind.schema.decisions import SearchCodeToolCallDecision
from forgemind.state.action_registry import InMemoryActionRegistry


def make_search_decision() -> SearchCodeToolCallDecision:
    return SearchCodeToolCallDecision(
        action_type="tool_call",
        tool_name="search_code",
        arguments={"query": "discount"},
        reason="定位折扣逻辑",
    )


def test_search_decision_normalizes_nested_arguments() -> None:
    decision = make_search_decision()

    assert decision.arguments.scope == "."
    assert decision.arguments.max_results == 20


def test_search_decision_rejects_agent_supplied_action_id() -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeToolCallDecision.model_validate(
            {
                "action_id": "agent-action-001",
                "action_type": "tool_call",
                "tool_name": "search_code",
                "arguments": {"query": "discount"},
                "reason": "定位折扣逻辑",
            }
        )

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_runtime_accepts_and_registers_search_decision() -> None:
    decision = make_search_decision()
    registry = InMemoryActionRegistry()

    accepted = accept_and_register_search_code_decision(
        decision,
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: "action-search-001",
    )

    assert isinstance(accepted, AcceptedSearchCodeToolAction)
    assert accepted.action_id == "action-search-001"
    assert accepted.task_id == "task-001"
    assert accepted.arguments is decision.arguments
    assert registry.get("action-search-001") is accepted


def test_search_action_id_collision_retries_without_overwriting() -> None:
    registry = InMemoryActionRegistry()
    original = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/original.py"},
        reason="保留原始读取",
    )
    registry.register(original)
    generated_ids = iter(["action-001", "action-002"])

    accepted = accept_and_register_search_code_decision(
        make_search_decision(),
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: next(generated_ids),
    )

    assert registry.get("action-001") is original
    assert registry.get("action-002") is accepted
