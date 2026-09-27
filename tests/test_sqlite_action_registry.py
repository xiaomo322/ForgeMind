from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
    AcceptedRunCommandToolAction,
)
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.run_command import RunCommandArguments
from forgemind.state.action_registry import DuplicateActionIdError
from forgemind.state.sqlite_action_registry import (
    CorruptStoredActionError,
    SQLiteActionRegistry,
)


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
    first_process = SQLiteActionRegistry(database_path)
    first_process.register(action)

    second_process = SQLiteActionRegistry(database_path)
    restored = second_process.get(action.action_id)

    assert restored == action
    assert restored is not action
    assert type(restored) is type(action)


def test_duplicate_action_id_does_not_overwrite_disk_record(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    registry = SQLiteActionRegistry(database_path)
    original = _read_action("duplicate-id")
    conflicting = _command_action("duplicate-id")
    registry.register(original)

    with pytest.raises(DuplicateActionIdError):
        registry.register(conflicting)

    assert SQLiteActionRegistry(database_path).get("duplicate-id") == original


def test_missing_action_id_raises_key_error(tmp_path: Path) -> None:
    registry = SQLiteActionRegistry(tmp_path / "state.db")

    with pytest.raises(KeyError):
        registry.get("missing-action")


def test_corrupt_action_json_is_not_returned_as_authoritative_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    registry = SQLiteActionRegistry(database_path)
    action = _read_action()
    registry.register(action)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE actions SET payload_json = ? WHERE action_id = ?",
            ('{"tool_name":"unknown"}', action.action_id),
        )

    with pytest.raises(CorruptStoredActionError) as caught:
        SQLiteActionRegistry(database_path).get(action.action_id)

    assert caught.value.action_id == action.action_id
    assert caught.value.error_count > 0
