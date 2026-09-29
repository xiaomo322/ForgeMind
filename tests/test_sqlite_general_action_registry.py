from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.tasks import TaskRecord
from forgemind.state.sqlite_action_registry import (
    CorruptStoredActionError,
    SQLiteActionRegistry,
)
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry


def _registry(database_path: Path, project_root: Path) -> SQLiteActionRegistry:
    tasks = SQLiteTaskRegistry(database_path)
    try:
        tasks.get("task-ask-001")
    except KeyError:
        tasks.register(
            TaskRecord(
                task_id="task-ask-001",
                original_request="确认折扣叠加规则",
                project_root=str(project_root.resolve()),
            )
        )
    return SQLiteActionRegistry(database_path)


def _ask_action() -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id="action-ask-001",
        task_id="task-ask-001",
        action_type="ask_user",
        reason="项目中没有折扣叠加规则",
        question="会员折扣和优惠券可以同时使用吗？",
        options=("可以", "不可以"),
    )


def test_ask_user_action_survives_sqlite_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    action = _ask_action()
    _registry(database_path, tmp_path).register(action)

    restored = _registry(database_path, tmp_path).get(action.action_id)

    assert restored == action
    assert restored is not action
    assert type(restored) is AcceptedAskUserAction


def test_ask_user_action_uses_null_tool_name_index(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    action = _ask_action()
    _registry(database_path, tmp_path).register(action)

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT action_type, tool_name
            FROM actions
            WHERE action_id = ?
            """,
            (action.action_id,),
        ).fetchone()

    assert row == ("ask_user", None)


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("action_type", "tool_call"),
        ("tool_name", "read_file"),
    ],
)
def test_ask_user_action_rejects_tampered_index_columns(
    tmp_path: Path,
    column: str,
    invalid_value: str,
) -> None:
    database_path = tmp_path / "state.db"
    action = _ask_action()
    _registry(database_path, tmp_path).register(action)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"UPDATE actions SET {column} = ? WHERE action_id = ?",
            (invalid_value, action.action_id),
        )

    with pytest.raises(CorruptStoredActionError):
        _registry(database_path, tmp_path).get(action.action_id)
