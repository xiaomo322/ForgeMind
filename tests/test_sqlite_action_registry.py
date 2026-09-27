from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
    AcceptedRunCommandToolAction,
)
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.run_command import RunCommandArguments
from forgemind.schema.tasks import TaskRecord
from forgemind.state.action_registry import DuplicateActionIdError
from forgemind.state.sqlite_action_registry import (
    CorruptStoredActionError,
    SQLiteActionRegistry,
)
from forgemind.state.sqlite_task_registry import (
    SQLiteTaskRegistry,
    UnknownTaskIdError,
)


def _actions(
    database_path: Path,
    project_root: Path,
    *,
    register_task: bool = True,
) -> SQLiteActionRegistry:
    tasks = SQLiteTaskRegistry(database_path)
    if register_task:
        try:
            tasks.get("task-001")
        except KeyError:
            tasks.register(
                TaskRecord(
                    task_id="task-001",
                    original_request="测试持久化 Action",
                    project_root=str(project_root.resolve()),
                )
            )
    return SQLiteActionRegistry(database_path)


def _read_action(
    action_id: str = "action-read-001",
) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments=ReadFileArguments(path="app.py", start_line=1, max_lines=20),
        reason="读取入口文件",
    )


def _command_action(
    action_id: str = "action-command-001",
) -> AcceptedRunCommandToolAction:
    return AcceptedRunCommandToolAction(
        action_id=action_id,
        task_id="task-001",
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-m", "compileall", "backend"),
            working_directory=".",
            timeout_seconds=30,
        ),
        reason="检查 Python 语法",
    )


@pytest.mark.parametrize("action", [_read_action(), _command_action()])
def test_action_survives_registry_restart(
    tmp_path: Path,
    action: AcceptedReadFileToolAction | AcceptedRunCommandToolAction,
) -> None:
    database_path = tmp_path / "state.db"
    first_process = _actions(database_path, tmp_path)
    first_process.register(action)

    second_process = _actions(database_path, tmp_path)
    restored = second_process.get(action.action_id)

    assert restored == action
    assert restored is not action
    assert type(restored) is type(action)


def test_duplicate_action_id_does_not_overwrite_disk_record(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    registry = _actions(database_path, tmp_path)
    original = _read_action("duplicate-id")
    conflicting = _command_action("duplicate-id")
    registry.register(original)

    with pytest.raises(DuplicateActionIdError):
        registry.register(conflicting)

    assert _actions(database_path, tmp_path).get("duplicate-id") == original


def test_missing_action_id_raises_key_error(tmp_path: Path) -> None:
    registry = _actions(tmp_path / "state.db", tmp_path)

    with pytest.raises(KeyError):
        registry.get("missing-action")


def test_corrupt_action_json_is_not_returned_as_authoritative_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    registry = _actions(database_path, tmp_path)
    action = _read_action()
    registry.register(action)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE actions SET payload_json = ? WHERE action_id = ?",
            ('{"tool_name":"unknown"}', action.action_id),
        )

    with pytest.raises(CorruptStoredActionError) as caught:
        _actions(database_path, tmp_path).get(action.action_id)

    assert caught.value.action_id == action.action_id
    assert caught.value.error_count > 0


def test_action_requires_persisted_task(tmp_path: Path) -> None:
    registry = _actions(
        tmp_path / "state.db",
        tmp_path,
        register_task=False,
    )

    with pytest.raises(UnknownTaskIdError):
        registry.register(_read_action())
