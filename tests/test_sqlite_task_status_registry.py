from pathlib import Path
import sqlite3

import pytest

from forgemind.runtime.task_status import InvalidTaskStatusTransitionError
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_task_registry import (
    SQLiteTaskRegistry,
    UnknownTaskIdError,
)
from forgemind.state.sqlite_task_status_registry import (
    CorruptStoredTaskStatusError,
    DuplicateTaskStatusIdError,
    InvalidInitialTaskStatusError,
    NonSequentialTaskStatusRevisionError,
    SQLiteTaskStatusRegistry,
)


def _registries(
    database_path: Path,
    project_root: Path,
) -> tuple[SQLiteTaskRegistry, SQLiteTaskStatusRegistry]:
    tasks = SQLiteTaskRegistry(database_path)
    statuses = SQLiteTaskStatusRegistry(database_path)
    return tasks, statuses


def _task(project_root: Path) -> TaskRecord:
    return TaskRecord(
        task_id="task-001",
        original_request="修复会员折扣没有生效的问题",
        project_root=str(project_root.resolve()),
    )


def _status(
    revision: int,
    status: TaskStatus,
    *,
    status_id: str | None = None,
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=status_id or f"status-{revision:03d}",
        task_id="task-001",
        revision=revision,
        status=status,
        reason=f"进入 {status.value}",
    )


def test_status_history_survives_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))
    initial = _status(1, TaskStatus.RUNNING)
    waiting = _status(2, TaskStatus.WAITING_USER)
    statuses.record(initial)
    statuses.record(waiting)

    restored = SQLiteTaskStatusRegistry(database_path).get_current("task-001")

    assert restored == waiting
    assert restored is not waiting
    assert SQLiteTaskStatusRegistry(database_path).get(initial.task_status_id) == initial


def test_status_requires_persisted_task(tmp_path: Path) -> None:
    _, statuses = _registries(tmp_path / "state.db", tmp_path)

    with pytest.raises(UnknownTaskIdError):
        statuses.record(_status(1, TaskStatus.RUNNING))


@pytest.mark.parametrize(
    "invalid_initial",
    [
        _status(2, TaskStatus.RUNNING),
        _status(1, TaskStatus.WAITING_USER),
    ],
)
def test_initial_status_must_be_revision_one_running(
    tmp_path: Path,
    invalid_initial: TaskStatusRecord,
) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))

    with pytest.raises(InvalidInitialTaskStatusError):
        statuses.record(invalid_initial)


def test_status_revision_must_be_continuous(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))
    statuses.record(_status(1, TaskStatus.RUNNING))

    with pytest.raises(NonSequentialTaskStatusRevisionError) as caught:
        statuses.record(_status(3, TaskStatus.WAITING_USER))

    assert caught.value.expected == 2
    assert caught.value.actual == 3


def test_status_transition_must_follow_runtime_rules(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))
    statuses.record(_status(1, TaskStatus.RUNNING))
    statuses.record(_status(2, TaskStatus.WAITING_USER))

    with pytest.raises(InvalidTaskStatusTransitionError):
        statuses.record(_status(3, TaskStatus.COMPLETED))


def test_get_current_requires_status_history(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))

    with pytest.raises(KeyError):
        statuses.get_current("task-001")


def test_duplicate_status_id_does_not_overwrite_history(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))
    initial = _status(1, TaskStatus.RUNNING)
    statuses.record(initial)

    with pytest.raises(DuplicateTaskStatusIdError):
        statuses.record(
            _status(
                2,
                TaskStatus.WAITING_USER,
                status_id=initial.task_status_id,
            )
        )

    assert statuses.get_current("task-001") == initial


def test_corrupt_current_status_is_rejected_before_next_transition(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    tasks, statuses = _registries(database_path, tmp_path)
    tasks.register(_task(tmp_path))
    initial = _status(1, TaskStatus.RUNNING)
    statuses.record(initial)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE task_statuses
            SET status = ?
            WHERE task_status_id = ?
            """,
            (TaskStatus.COMPLETED.value, initial.task_status_id),
        )

    with pytest.raises(CorruptStoredTaskStatusError):
        statuses.record(_status(2, TaskStatus.WAITING_USER))

    with pytest.raises(CorruptStoredTaskStatusError):
        statuses.get_current("task-001")
