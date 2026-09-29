from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.context.builder import (
    InvalidActionContextLimitError,
    build_agent_task_context,
)
from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.context import AgentTaskContext
from forgemind.schema.run_command import RunCommandArguments
from forgemind.schema.tasks import (
    ActionStateView,
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)


def _action_state(sequence: int) -> ActionStateView:
    action = AcceptedRunCommandToolAction(
        action_id=f"action-{sequence:03d}",
        task_id="task-context-001",
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-V",),
            working_directory=".",
            timeout_seconds=30,
        ),
        reason=f"上下文动作 {sequence}",
    )
    return ActionStateView(
        sequence=sequence,
        action=action,
        permission_request=None,
        permission_decision=None,
        observation=None,
    )


def _task_view(tmp_path: Path, action_count: int) -> TaskStateView:
    task = TaskRecord(
        task_id="task-context-001",
        original_request="构建有限且不误导 Agent 的任务上下文",
        project_root=str(tmp_path.resolve()),
    )
    status = TaskStatusRecord(
        task_status_id="status-context-001",
        task_id=task.task_id,
        revision=1,
        status=TaskStatus.RUNNING,
        reason="任务创建",
    )
    return TaskStateView(
        task=task,
        current_status=status,
        actions=tuple(
            _action_state(sequence)
            for sequence in range(1, action_count + 1)
        ),
    )


def test_builder_preserves_task_status_and_empty_history(
    tmp_path: Path,
) -> None:
    task_view = _task_view(tmp_path, action_count=0)

    context = build_agent_task_context(
        task_view,
        max_action_count=3,
    )

    assert context.task == task_view.task
    assert context.current_status == task_view.current_status
    assert context.recent_actions == ()
    assert context.total_action_count == 0
    assert context.omitted_action_count == 0
    assert context.is_action_history_complete is True


def test_builder_keeps_complete_history_within_limit(tmp_path: Path) -> None:
    task_view = _task_view(tmp_path, action_count=2)

    context = build_agent_task_context(
        task_view,
        max_action_count=2,
    )

    assert context.recent_actions == task_view.actions
    assert context.total_action_count == 2
    assert context.omitted_action_count == 0
    assert context.is_action_history_complete is True


def test_builder_keeps_latest_actions_and_marks_omission(
    tmp_path: Path,
) -> None:
    task_view = _task_view(tmp_path, action_count=5)

    context = build_agent_task_context(
        task_view,
        max_action_count=2,
    )

    print(
        "\nAgent Context："
        f"total={context.total_action_count}, "
        f"omitted={context.omitted_action_count}, "
        f"complete={context.is_action_history_complete}, "
        "recent_sequences="
        f"{[item.sequence for item in context.recent_actions]}"
    )
    assert [item.sequence for item in context.recent_actions] == [4, 5]
    assert context.total_action_count == 5
    assert context.omitted_action_count == 3
    assert context.is_action_history_complete is False


@pytest.mark.parametrize("invalid_limit", [0, -1, True, 1.5, "2"])
def test_builder_rejects_invalid_action_limit(
    tmp_path: Path,
    invalid_limit: object,
) -> None:
    with pytest.raises(InvalidActionContextLimitError):
        build_agent_task_context(
            _task_view(tmp_path, action_count=1),
            max_action_count=invalid_limit,  # type: ignore[arg-type]
        )


def test_context_rejects_inconsistent_history_metadata(
    tmp_path: Path,
) -> None:
    task_view = _task_view(tmp_path, action_count=2)

    with pytest.raises(ValidationError):
        AgentTaskContext(
            task=task_view.task,
            current_status=task_view.current_status,
            recent_actions=task_view.actions,
            total_action_count=2,
            omitted_action_count=1,
            is_action_history_complete=False,
        )
