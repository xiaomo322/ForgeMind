from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from forgemind.runtime.acceptance import (
    accept_and_register_run_command_decision,
)
from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.decisions import RunCommandToolCallDecision
from forgemind.schema.run_command import RunCommandArguments
from forgemind.state.action_registry import InMemoryActionRegistry


def _decision() -> RunCommandToolCallDecision:
    return RunCommandToolCallDecision(
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-m", "compileall", "backend"),
            working_directory=".",
        ),
        reason="编译 backend 目录，检查 Python 语法",
    )


def _id_factory(values: Iterator[str]):
    return lambda: next(values)


def test_run_command_decision_uses_strict_nested_arguments() -> None:
    decision = _decision()

    assert decision.arguments.program == "python"
    assert decision.arguments.timeout_seconds == 120


def test_run_command_decision_rejects_agent_supplied_action_id() -> None:
    with pytest.raises(ValidationError):
        RunCommandToolCallDecision(
            action_id="agent-action-1",
            action_type="tool_call",
            tool_name="run_command",
            arguments=RunCommandArguments(
                program="python",
                working_directory=".",
            ),
            reason="检查 Python 版本",
        )


def test_accept_and_register_run_command_preserves_decision_arguments() -> None:
    decision = _decision()
    registry = InMemoryActionRegistry()

    action = accept_and_register_run_command_decision(
        decision,
        task_id="task-1",
        registry=registry,
        next_action_id=lambda: "action-1",
    )

    assert isinstance(action, AcceptedRunCommandToolAction)
    assert action.action_id == "action-1"
    assert action.task_id == "task-1"
    assert action.arguments is decision.arguments
    assert registry.get("action-1") is action


def test_run_command_registration_retries_without_overwriting_collision() -> None:
    registry = InMemoryActionRegistry()
    first = accept_and_register_run_command_decision(
        _decision(),
        task_id="task-original",
        registry=registry,
        next_action_id=lambda: "duplicate-id",
    )

    second = accept_and_register_run_command_decision(
        _decision(),
        task_id="task-new",
        registry=registry,
        next_action_id=_id_factory(iter(("duplicate-id", "unique-id"))),
    )

    assert registry.get("duplicate-id") is first
    assert second.action_id == "unique-id"
    assert registry.get("unique-id") is second
