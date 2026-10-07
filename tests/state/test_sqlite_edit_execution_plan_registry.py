from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.execution import EditExecutionPlan
from forgemind.schema.tasks import TaskRecord
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_edit_execution_plan_registry import (
    CorruptStoredEditExecutionPlanError,
    DuplicateEditExecutionPlanError,
    EditExecutionPlanActionSnapshotMismatchError,
    SQLiteEditExecutionPlanRegistry,
)
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry


def _action() -> AcceptedEditFileToolAction:
    return AcceptedEditFileToolAction(
        action_id="action-edit-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments=EditFileArguments(
            path="app.py",
            old_text="old",
            new_text="new",
            expected_version="sha256:before",
        ),
        reason="更新实现",
    )


def _plan(action: AcceptedEditFileToolAction | None = None) -> EditExecutionPlan:
    action = _action() if action is None else action
    return EditExecutionPlan(
        action_id=action.action_id,
        task_id=action.task_id,
        path=action.arguments.path,
        before_version=action.arguments.expected_version,
        after_version="sha256:after",
        diff="--- app.py\n+++ app.py\n@@\n-old\n+new\n",
    )


def _registries(
    database_path: Path,
) -> tuple[SQLiteActionRegistry, SQLiteEditExecutionPlanRegistry]:
    tasks = SQLiteTaskRegistry(database_path)
    try:
        tasks.get("task-001")
    except KeyError:
        tasks.register(
            TaskRecord(
                task_id="task-001",
                original_request="更新实现",
                project_root=str(database_path.parent.resolve()),
            )
        )
    actions = SQLiteActionRegistry(database_path)
    return actions, SQLiteEditExecutionPlanRegistry(database_path, actions)


def test_edit_execution_plan_survives_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    actions, plans = _registries(database_path)
    action = _action()
    plan = _plan(action)
    actions.register(action)
    plans.register(plan)

    _, reopened = _registries(database_path)

    assert reopened.get(action.action_id) == plan


def test_action_can_have_only_one_edit_execution_plan(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    actions, plans = _registries(database_path)
    action = _action()
    actions.register(action)
    plans.register(_plan(action))

    with pytest.raises(DuplicateEditExecutionPlanError):
        plans.register(_plan(action).model_copy(update={"diff": "different"}))


def test_plan_must_match_persisted_edit_action_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    actions, plans = _registries(database_path)
    action = _action()
    actions.register(action)

    with pytest.raises(EditExecutionPlanActionSnapshotMismatchError):
        plans.register(_plan(action).model_copy(update={"path": "other.py"}))


def test_corrupt_plan_index_columns_are_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    actions, plans = _registries(database_path)
    action = _action()
    plan = _plan(action)
    actions.register(action)
    plans.register(plan)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE edit_execution_plans SET after_version = ? WHERE action_id = ?",
            ("sha256:tampered", action.action_id),
        )

    with pytest.raises(CorruptStoredEditExecutionPlanError):
        plans.get(action.action_id)
