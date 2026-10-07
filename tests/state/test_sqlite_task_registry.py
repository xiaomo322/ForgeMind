from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.tasks import TaskRecord
from forgemind.state.sqlite_task_registry import (
    CorruptStoredTaskError,
    DuplicateTaskIdError,
    SQLiteTaskRegistry,
)


def _task(project_root: Path, task_id: str = "task-001") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        original_request="修复会员折扣没有生效的问题",
        project_root=str(project_root.resolve()),
    )


def test_task_survives_registry_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    task = _task(tmp_path)
    SQLiteTaskRegistry(database_path).register(task)

    restored = SQLiteTaskRegistry(database_path).get(task.task_id)

    assert restored == task
    assert restored is not task


def test_duplicate_task_id_does_not_overwrite_original(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    registry = SQLiteTaskRegistry(database_path)
    original = _task(tmp_path, "task-duplicate")
    conflicting = original.model_copy(
        update={"original_request": "删除整个项目"}
    )
    registry.register(original)

    with pytest.raises(DuplicateTaskIdError):
        registry.register(conflicting)

    assert registry.get(original.task_id) == original


def test_missing_task_id_raises_key_error(tmp_path: Path) -> None:
    registry = SQLiteTaskRegistry(tmp_path / "state.db")

    with pytest.raises(KeyError):
        registry.get("missing-task")


def test_corrupt_task_json_is_not_returned(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    registry = SQLiteTaskRegistry(database_path)
    task = _task(tmp_path)
    registry.register(task)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
            ('{"task_id": 123}', task.task_id),
        )

    with pytest.raises(CorruptStoredTaskError) as caught:
        SQLiteTaskRegistry(database_path).get(task.task_id)

    assert caught.value.task_id == task.task_id
    assert caught.value.error_count > 0


def test_mismatched_task_index_column_is_not_returned(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    registry = SQLiteTaskRegistry(database_path)
    task = _task(tmp_path)
    registry.register(task)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE tasks SET project_root = ? WHERE task_id = ?",
            (str((tmp_path / "other").resolve()), task.task_id),
        )

    with pytest.raises(CorruptStoredTaskError) as caught:
        SQLiteTaskRegistry(database_path).get(task.task_id)

    assert caught.value.task_id == task.task_id
    assert caught.value.error_count == 0
