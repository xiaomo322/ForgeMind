from uuid import UUID

import pytest

from forgemind.runtime.acceptance import (
    ActionIdAllocationError,
    accept_and_register_read_file_decision,
    accept_read_file_decision,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.decisions import ReadFileToolCallDecision
from forgemind.state.action_registry import InMemoryActionRegistry


def test_runtime_accepts_decision_with_runtime_generated_ids() -> None:
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )
    generated_ids: list[str] = []

    def next_action_id() -> str:
        generated_ids.append("action-001")
        return "action-001"

    accepted = accept_read_file_decision(
        decision,
        task_id="task-001",
        next_action_id=next_action_id,
    )

    assert generated_ids == ["action-001"]
    assert accepted.action_id == "action-001"
    assert accepted.task_id == "task-001"
    assert accepted.arguments is decision.arguments


def test_runtime_acceptance_uses_uuid_generator_by_default() -> None:
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )

    accepted = accept_read_file_decision(decision, task_id="task-001")

    prefix = "action_"
    assert accepted.action_id.startswith(prefix)
    assert UUID(accepted.action_id.removeprefix(prefix)).version == 4


def test_runtime_retries_when_registry_rejects_duplicate_id() -> None:
    registry = InMemoryActionRegistry()
    registry.register(
        AcceptedReadFileToolAction.model_validate(
            {
                "action_id": "action-001",
                "task_id": "task-001",
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/original.py"},
                "reason": "保留原始 Action",
            }
        )
    )
    generated_ids = iter(["action-001", "action-002"])
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/new.py"},
            "reason": "读取新文件",
        }
    )

    accepted = accept_and_register_read_file_decision(
        decision,
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: next(generated_ids),
    )

    assert accepted.action_id == "action-002"
    assert registry.get("action-001").arguments.path == "src/original.py"
    assert registry.get("action-002") is accepted


def test_runtime_stops_after_action_id_retry_limit() -> None:
    registry = InMemoryActionRegistry()
    registry.register(
        AcceptedReadFileToolAction.model_validate(
            {
                "action_id": "action-001",
                "task_id": "task-001",
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/original.py"},
                "reason": "保留原始 Action",
            }
        )
    )
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/new.py"},
            "reason": "读取新文件",
        }
    )

    with pytest.raises(ActionIdAllocationError):
        accept_and_register_read_file_decision(
            decision,
            task_id="task-001",
            registry=registry,
            next_action_id=lambda: "action-001",
            max_id_attempts=3,
        )

    assert registry.get("action-001").arguments.path == "src/original.py"
