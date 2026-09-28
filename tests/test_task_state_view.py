from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_task_state_view_rejects_status_from_another_task(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path, "task-001"),
            current_status=_initial("task-other"),
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
    )
    assert restored.task is not task
    assert restored.current_status is not initial


def test_state_view_requires_existing_task(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")

    with pytest.raises(KeyError):
        state.get_task_view("missing-task")
