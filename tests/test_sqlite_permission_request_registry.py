from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.permissions import PendingRunCommandPermissionRequest
from forgemind.schema.run_command import RunCommandArguments
from forgemind.schema.tasks import TaskRecord
from forgemind.state.permission_request_registry import (
    DuplicatePermissionRequestIdError,
    PermissionRequestActionSnapshotMismatchError,
    UnknownPermissionRequestActionError,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_permission_request_registry import (
    CorruptStoredPermissionRequestError,
    SQLitePermissionRequestRegistry,
    SQLiteRegistryDatabaseMismatchError,
)
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry


def _action() -> AcceptedRunCommandToolAction:
    return AcceptedRunCommandToolAction(
        action_id="action-command-001",
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


def _request(
    action: AcceptedRunCommandToolAction,
    *,
    permission_request_id: str = "permission-command-001",
    arguments: RunCommandArguments | None = None,
) -> PendingRunCommandPermissionRequest:
    return PendingRunCommandPermissionRequest(
        permission_request_id=permission_request_id,
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments if arguments is None else arguments,
        reason="命令会执行项目代码，需要用户确认",
        basis_ids=("policy-run-command-001",),
    )


def _registries(
    database_path: Path,
) -> tuple[SQLiteActionRegistry, SQLitePermissionRequestRegistry]:
    tasks = SQLiteTaskRegistry(database_path)
    try:
        tasks.get("task-001")
    except KeyError:
        tasks.register(
            TaskRecord(
                task_id="task-001",
                original_request="测试权限请求持久化",
                project_root=str(database_path.parent.resolve()),
            )
        )
    actions = SQLiteActionRegistry(database_path)
    requests = SQLitePermissionRequestRegistry(database_path, actions)
    return actions, requests


def test_permission_request_survives_registry_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    actions, requests = _registries(database_path)
    action = _action()
    request = _request(action)
    actions.register(action)
    requests.register(request)

    restarted_actions, restarted_requests = _registries(database_path)
    restored = restarted_requests.get(request.permission_request_id)

    assert restarted_actions.get(action.action_id) == action
    assert restored == request
    assert restored is not request
    assert restored.arguments == action.arguments


def test_permission_request_requires_persisted_action(tmp_path: Path) -> None:
    _, requests = _registries(tmp_path / "state.db")
    request = _request(_action())

    with pytest.raises(UnknownPermissionRequestActionError):
        requests.register(request)


def test_permission_request_rejects_changed_action_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    actions, requests = _registries(database_path)
    action = _action()
    actions.register(action)
    changed_arguments = RunCommandArguments(
        program="python",
        args=("cleanup.py",),
        working_directory=".",
        timeout_seconds=30,
    )

    with pytest.raises(PermissionRequestActionSnapshotMismatchError):
        requests.register(_request(action, arguments=changed_arguments))


def test_duplicate_permission_request_does_not_overwrite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    actions, requests = _registries(database_path)
    action = _action()
    original = _request(action)
    actions.register(action)
    requests.register(original)
    conflicting = original.model_copy(
        update={"reason": "另一条询问不能覆盖原记录"}
    )

    with pytest.raises(DuplicatePermissionRequestIdError):
        requests.register(conflicting)

    assert requests.get(original.permission_request_id) == original


def test_permission_registry_requires_same_database(tmp_path: Path) -> None:
    SQLiteTaskRegistry(tmp_path / "actions.db").register(
        TaskRecord(
            task_id="task-001",
            original_request="测试数据库一致性",
            project_root=str(tmp_path.resolve()),
        )
    )
    actions = SQLiteActionRegistry(tmp_path / "actions.db")

    with pytest.raises(SQLiteRegistryDatabaseMismatchError):
        SQLitePermissionRequestRegistry(tmp_path / "requests.db", actions)


def test_corrupt_permission_request_columns_are_rejected(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    actions, requests = _registries(database_path)
    action = _action()
    request = _request(action)
    actions.register(action)
    requests.register(request)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE permission_requests
            SET task_id = ?
            WHERE permission_request_id = ?
            """,
            ("tampered-task", request.permission_request_id),
        )

    with pytest.raises(CorruptStoredPermissionRequestError):
        requests.get(request.permission_request_id)
