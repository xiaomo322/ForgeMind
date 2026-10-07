from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
)
from forgemind.schema.permissions import (
    PendingEditFilePermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
)


def _waiting_state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-reject-001",
        original_request="修改折扣",
        project_root=str(tmp_path.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-running-001",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    action = _action()
    state.record_tool_permission_waiting(
        action,
        PendingEditFilePermissionRequest(
            permission_request_id="permission-edit-001",
            task_id=action.task_id,
            action_id=action.action_id,
            status="pending",
            action_type=action.action_type,
            tool_name=action.tool_name,
            arguments=action.arguments,
            reason="修改文件需要用户确认",
            basis_ids=("policy:edit_file:user-confirmation:v0.1",),
        ),
        TaskStatusRecord(
            task_status_id="status-waiting-002",
            task_id=task.task_id,
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="等待用户确认文件修改",
        ),
    )
    return state


def _action() -> AcceptedEditFileToolAction:
    return AcceptedEditFileToolAction(
        action_id="action-edit-001",
        task_id="task-reject-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "app.py",
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": "sha256:before",
        },
        reason="修改折扣",
    )


def _decision() -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        permission_decision_id="decision-reject-001",
        permission_request_id="permission-edit-001",
        task_id="task-reject-001",
        action_id="action-edit-001",
        decision=PermissionDecision.REJECT,
        source="user",
        raw_response="不同意这次修改",
    )


def _observation() -> RejectedObservation:
    return RejectedObservation(
        action_id="action-edit-001",
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户已拒绝待确认权限请求",
            details=(
                ObservationErrorDetail(
                    key="permission_basis_id",
                    value="decision-reject-001",
                ),
            ),
        ),
    )


def _running(
    task_status_id: str = "status-running-003",
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=task_status_id,
        task_id="task-reject-001",
        revision=3,
        status=TaskStatus.RUNNING,
        reason="用户拒绝本次修改，继续评估其他方案",
    )


def test_rejection_decision_observation_and_running_are_atomic(
    tmp_path: Path,
) -> None:
    state = _waiting_state(tmp_path)

    state.record_permission_rejection_running(
        _decision(),
        _observation(),
        _running(),
    )

    restored = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view("task-reject-001")
    action_state = restored.actions[0]
    assert restored.current_status == _running()
    assert action_state.permission_decision == _decision()
    assert action_state.observation == _observation()


def test_status_conflict_rolls_back_rejection_decision_and_observation(
    tmp_path: Path,
) -> None:
    state = _waiting_state(tmp_path)

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_permission_rejection_running(
            _decision(),
            _observation(),
            _running(task_status_id="status-waiting-002"),
        )

    with pytest.raises(KeyError):
        state.permission_decisions.get(
            _decision().permission_decision_id
        )
    with pytest.raises(KeyError):
        state.observations.get(_action().action_id)
    assert state.task_statuses.get_current("task-reject-001").status is (
        TaskStatus.WAITING_USER
    )
