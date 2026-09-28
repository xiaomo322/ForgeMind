from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
    SequencedActionRecord,
)
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.tasks import (
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _task(tmp_path: Path, task_id: str = "task-001") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        original_request="修复会员折扣没有生效的问题",
        project_root=str(tmp_path.resolve()),
    )


def _initial(task_id: str = "task-001") -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id="status-001",
        task_id=task_id,
        revision=1,
        status=TaskStatus.RUNNING,
        reason="任务创建",
    )


def _action(
    action_id: str,
    task_id: str = "task-001",
) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id=task_id,
        action_type="tool_call",
        tool_name="read_file",
        arguments=ReadFileArguments(
            path=f"{action_id}.py",
            start_line=1,
            max_lines=20,
        ),
        reason=f"读取 {action_id}",
    )


def test_task_state_view_rejects_status_from_another_task(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path, "task-001"),
            current_status=_initial("task-other"),
            actions=(),
        )


def test_task_state_view_rejects_action_from_another_task(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path, "task-001"),
            current_status=_initial("task-001"),
            actions=(
                SequencedActionRecord(
                    sequence=1,
                    action=_action("action-001", "task-other"),
                ),
            ),
        )


def test_task_state_view_rejects_non_continuous_action_sequence(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path),
            current_status=_initial(),
            actions=(
                SequencedActionRecord(
                    sequence=2,
                    action=_action("action-002"),
                ),
            ),
        )


def test_state_restores_task_current_view_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    first = SQLiteForgeMindState.open(database_path)
    task = _task(tmp_path)
    initial = _initial()
    first.create_task(task, initial)

    restored = SQLiteForgeMindState.open(database_path).get_task_view(
        task.task_id
    )

    assert restored == TaskStateView(
        task=task,
        current_status=initial,
        actions=(),
    )
    assert restored.task is not task
    assert restored.current_status is not initial


def test_state_view_requires_existing_task(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")

    with pytest.raises(KeyError):
        state.get_task_view("missing-task")


def test_state_view_restores_actions_in_registration_order(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    first = SQLiteForgeMindState.open(database_path)
    first.create_task(_task(tmp_path), _initial())
    first_action = _action("z-last-lexically")
    second_action = _action("a-first-lexically")
    first.actions.register(first_action)
    first.actions.register(second_action)

    restored = SQLiteForgeMindState.open(database_path).get_task_view(
        "task-001"
    )

    assert restored.actions == (
        SequencedActionRecord(sequence=1, action=first_action),
        SequencedActionRecord(sequence=2, action=second_action),
    )
