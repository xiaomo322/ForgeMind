from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
)
from forgemind.schema.permissions import (
    PendingEditFilePermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.state.sqlite_task_status_registry import DuplicateTaskStatusIdError


def _waiting_state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="修改文件",
            project_root=str(tmp_path.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="status-001",
            task_id="task-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    action = AcceptedEditFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "missing.py",
            "old_text": "value = 1",
            "new_text": "value = 2",
            "expected_version": "sha256:before",
        },
        reason="修改文件",
    )
    state.record_tool_permission_waiting(
        action,
        PendingEditFilePermissionRequest(
            permission_request_id="request-001",
            task_id="task-001",
            action_id="action-001",
            status="pending",
            action_type="tool_call",
            tool_name="edit_file",
            arguments=action.arguments,
            reason="修改文件需要批准",
            basis_ids=("policy:edit",),
        ),
        TaskStatusRecord(
            task_status_id="status-002",
            task_id="task-001",
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="等待批准",
        ),
    )
    return state


def _decision() -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        permission_decision_id="decision-001",
        permission_request_id="request-001",
        task_id="task-001",
        action_id="action-001",
        decision=PermissionDecision.APPROVE,
        source="user",
        raw_response="批准并执行",
    )


def _observation() -> FailedObservation:
    return FailedObservation(
        action_id="action-001",
        status="failed",
        error=ObservationError(
            code=ObservationErrorCode.FILE_NOT_FOUND,
            message="目标文件不存在",
        ),
    )


def _running(status_id: str = "status-003") -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=status_id,
        task_id="task-001",
        revision=3,
        status=TaskStatus.RUNNING,
        reason="edit_file 执行前检查失败：FILE_NOT_FOUND",
    )


def test_approval_failure_decision_observation_and_running_are_atomic(
    tmp_path: Path,
) -> None:
    state = _waiting_state(tmp_path)

    state.record_permission_approval_failure_running(
        _decision(),
        _observation(),
        _running(),
    )

    view = SQLiteForgeMindState.open(state.database_path).get_task_view("task-001")
    assert view.current_status == _running()
    assert view.actions[0].permission_decision == _decision()
    assert view.actions[0].observation == _observation()


def test_status_conflict_rolls_back_approval_failure_facts(tmp_path: Path) -> None:
    state = _waiting_state(tmp_path)

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_permission_approval_failure_running(
            _decision(),
            _observation(),
            _running(status_id="status-002"),
        )

    with pytest.raises(KeyError):
        state.permission_decisions.get("decision-001")
    with pytest.raises(KeyError):
        state.observations.get("action-001")
    assert state.task_statuses.get_current("task-001").status is TaskStatus.WAITING_USER
