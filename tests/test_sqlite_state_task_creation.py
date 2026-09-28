from pathlib import Path

import pytest

from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import (
    SQLiteForgeMindState,
    TaskStatusTaskMismatchError,
)
from forgemind.state.sqlite_task_registry import DuplicateTaskIdError
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
    InvalidInitialTaskStatusError,
)


def _task(project_root: Path, task_id: str) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        original_request=f"处理任务 {task_id}",
        project_root=str(project_root.resolve()),
    )


def _initial_status(
    task_id: str,
    status_id: str,
    *,
    revision: int = 1,
    status: TaskStatus = TaskStatus.RUNNING,
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=status_id,
        task_id=task_id,
        revision=revision,
        status=status,
        reason="任务创建并开始执行",
    )


def test_create_task_atomically_persists_task_and_initial_status(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    state = SQLiteForgeMindState.open(database_path)
    task = _task(tmp_path, "task-001")
    initial = _initial_status(task.task_id, "status-001")

    state.create_task(task, initial)

    restarted = SQLiteForgeMindState.open(database_path)
    assert restarted.tasks.get(task.task_id) == task
    assert restarted.task_statuses.get_current(task.task_id) == initial


def test_create_task_rejects_mismatched_initial_status(
    tmp_path: Path,
) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = _task(tmp_path, "task-001")
    initial = _initial_status("task-other", "status-001")

    with pytest.raises(TaskStatusTaskMismatchError):
        state.create_task(task, initial)

    with pytest.raises(KeyError):
        state.tasks.get(task.task_id)


def test_create_task_requires_initial_running_revision_one(
    tmp_path: Path,
) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = _task(tmp_path, "task-001")
    invalid = _initial_status(
        task.task_id,
        "status-001",
        revision=2,
        status=TaskStatus.WAITING_USER,
    )

    with pytest.raises(InvalidInitialTaskStatusError):
        state.create_task(task, invalid)

    with pytest.raises(KeyError):
        state.tasks.get(task.task_id)


def test_status_conflict_rolls_back_new_task_insert(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    first_task = _task(tmp_path, "task-001")
    shared_status_id = "status-shared"
    state.create_task(
        first_task,
        _initial_status(first_task.task_id, shared_status_id),
    )
    second_task = _task(tmp_path, "task-002")

    with pytest.raises(DuplicateTaskStatusIdError):
        state.create_task(
            second_task,
            _initial_status(second_task.task_id, shared_status_id),
        )

    with pytest.raises(KeyError):
        state.tasks.get(second_task.task_id)


def test_duplicate_task_id_does_not_add_second_initial_status(
    tmp_path: Path,
) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = _task(tmp_path, "task-001")
    initial = _initial_status(task.task_id, "status-001")
    state.create_task(task, initial)

    with pytest.raises(DuplicateTaskIdError):
        state.create_task(
            task,
            _initial_status(task.task_id, "status-002"),
        )

    assert state.task_statuses.get_current(task.task_id) == initial
    with pytest.raises(KeyError):
        state.task_statuses.get("status-002")
