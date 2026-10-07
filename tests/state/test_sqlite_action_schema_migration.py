from pathlib import Path
import sqlite3

from forgemind.schema.actions import (
    AcceptedAskUserAction,
    AcceptedReadFileToolAction,
)
from forgemind.schema.tasks import TaskRecord
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry


def _legacy_action() -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id="action-legacy-001",
        task_id="task-migration-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
        reason="旧版本读取记录",
    )


def _create_legacy_database(database_path: Path, project_root: Path) -> None:
    SQLiteTaskRegistry(database_path).register(
        TaskRecord(
            task_id="task-migration-001",
            original_request="迁移旧 Action 表",
            project_root=str(project_root.resolve()),
        )
    )
    action = _legacy_action()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE actions (
                action_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_sequence INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE (task_id, task_sequence),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                action_id,
                task_id,
                task_sequence,
                tool_name,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                action.action_id,
                action.task_id,
                1,
                action.tool_name,
                action.model_dump_json(),
            ),
        )


def test_legacy_action_survives_schema_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    _create_legacy_database(database_path, tmp_path)

    registry = SQLiteActionRegistry(database_path)

    restored = registry.get("action-legacy-001")
    assert restored == _legacy_action()
    assert registry.list_for_task("task-migration-001")[0].sequence == 1


def test_migrated_table_accepts_ask_user_as_next_action(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    _create_legacy_database(database_path, tmp_path)
    registry = SQLiteActionRegistry(database_path)
    ask_action = AcceptedAskUserAction(
        action_id="action-ask-002",
        task_id="task-migration-001",
        action_type="ask_user",
        reason="缺少业务规则",
        question="折扣可以叠加吗？",
    )

    registry.register(ask_action)

    actions = registry.list_for_task("task-migration-001")
    assert tuple(item.sequence for item in actions) == (1, 2)
    assert actions[1].action == ask_action


def test_migration_makes_tool_name_nullable_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    _create_legacy_database(database_path, tmp_path)

    SQLiteActionRegistry(database_path)
    SQLiteActionRegistry(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = connection.execute("PRAGMA table_info(actions)").fetchall()

    columns_by_name = {row[1]: row for row in columns}
    assert "action_type" in columns_by_name
    assert columns_by_name["tool_name"][3] == 0
