from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.permissions import PendingEditFilePermissionRequest
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.permission_request_registry import (
    PermissionRequestActionSnapshotMismatchError,
)
from forgemind.state.sqlite_state import (
    InvalidToolPermissionWaitingStatusError,
    SQLiteForgeMindState,
    ToolPermissionWaitingTaskMismatchError,
)
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
)


def _state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    state.create_task(
        TaskRecord(
            task_id="task-edit-001",
            original_request="修正折扣计算",
            project_root=str(tmp_path.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="status-running-001",
            task_id="task-edit-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state


def _action() -> AcceptedEditFileToolAction:
    return AcceptedEditFileToolAction(
        action_id="action-edit-001",
        task_id="task-edit-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "app.py",
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": "sha256:before",
        },
        reason="修正折扣计算",
    )


def _request() -> PendingEditFilePermissionRequest:
    action = _action()
    return PendingEditFilePermissionRequest(
        permission_request_id="permission-edit-001",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments,
        reason="修改文件需要用户确认",
        basis_ids=("policy:edit_file:user-confirmation:v0.1",),
    )


def _waiting(
    task_status_id: str = "status-waiting-002",
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=task_status_id,
        task_id="task-edit-001",
        revision=2,
        status=TaskStatus.WAITING_USER,
        reason="等待用户确认文件修改",
    )


def test_tool_action_request_and_waiting_status_are_recorded_atomically(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    state.record_tool_permission_waiting(
        _action(),
        _request(),
        _waiting(),
    )

    restored = SQLiteForgeMindState.open(
        tmp_path / "state.db"
    ).get_task_view("task-edit-001")
    assert restored.current_status == _waiting()
    assert restored.actions[0].action == _action()
    assert restored.actions[0].permission_request == _request()
    assert restored.actions[0].observation is None


def test_status_conflict_rolls_back_action_and_permission_request(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_tool_permission_waiting(
            _action(),
            _request(),
            _waiting(task_status_id="status-running-001"),
        )

    with pytest.raises(KeyError):
        state.actions.get(_action().action_id)
    with pytest.raises(KeyError):
        state.permission_requests.get(_request().permission_request_id)
    assert state.task_statuses.get_current("task-edit-001").status is (
        TaskStatus.RUNNING
    )


def test_tool_permission_waiting_requires_same_task(tmp_path: Path) -> None:
    state = _state(tmp_path)
    wrong_status = _waiting().model_copy(update={"task_id": "task-other"})

    with pytest.raises(ToolPermissionWaitingTaskMismatchError):
        state.record_tool_permission_waiting(
            _action(),
            _request(),
            wrong_status,
        )


def test_tool_permission_waiting_requires_exact_action_snapshot(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    changed_request = _request().model_copy(
        update={
            "arguments": _request().arguments.model_copy(
                update={"new_text": "discount = 3"}
            )
        }
    )

    with pytest.raises(PermissionRequestActionSnapshotMismatchError):
        state.record_tool_permission_waiting(
            _action(),
            changed_request,
            _waiting(),
        )


def test_tool_permission_waiting_requires_waiting_user_status(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    wrong_status = _waiting().model_copy(
        update={"status": TaskStatus.COMPLETED}
    )

    with pytest.raises(InvalidToolPermissionWaitingStatusError):
        state.record_tool_permission_waiting(
            _action(),
            _request(),
            wrong_status,
        )
