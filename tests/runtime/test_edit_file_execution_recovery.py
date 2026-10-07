from pathlib import Path

import pytest

from forgemind.runtime.permission_approvals import resume_edit_execution
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.execution import EditExecutionPlan
from forgemind.schema.permissions import (
    PendingEditFilePermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.tools.edit_file import prepare_edit_from_snapshot


def _executing_state(tmp_path: Path) -> tuple[SQLiteForgeMindState, Path, bytes, bytes]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    target = project_root / "app.py"
    before = b"value = 1\n"
    after = b"value = 2\n"
    target.write_bytes(before)
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="更新 value",
            project_root=str(project_root.resolve()),
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
            "path": "app.py",
            "old_text": "value = 1",
            "new_text": "value = 2",
            "expected_version": calculate_content_version(before),
        },
        reason="更新值",
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
            reason="等待批准",
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
    prepared = prepare_edit_from_snapshot(action, content=before)
    state.record_permission_approval_executing(
        PermissionDecisionRecord(
            permission_decision_id="decision-001",
            permission_request_id="request-001",
            task_id="task-001",
            action_id="action-001",
            decision=PermissionDecision.APPROVE,
            source="user",
            raw_response="同意",
        ),
        EditExecutionPlan(
            action_id="action-001",
            task_id="task-001",
            path="app.py",
            before_version=prepared.before_version,
            after_version=prepared.after_version,
            diff=prepared.diff,
        ),
        TaskStatusRecord(
            task_status_id="status-003",
            task_id="task-001",
            revision=3,
            status=TaskStatus.EXECUTING,
            reason="执行修改",
        ),
    )
    return state, target, before, after


@pytest.mark.parametrize("already_written", [False, True])
def test_resume_reconciles_before_or_after_version_without_double_write(
    tmp_path: Path,
    already_written: bool,
) -> None:
    state, target, _, after = _executing_state(tmp_path)
    if already_written:
        target.write_bytes(after)

    result = resume_edit_execution(
        task_id="task-001",
        action_id="action-001",
        state=SQLiteForgeMindState.open(state.database_path),
        next_task_status_id=lambda: "status-004",
    )

    assert result.status == "success"
    assert target.read_bytes() == after
    assert state.task_statuses.get_current("task-001").status is TaskStatus.RUNNING


def test_resume_preserves_unexpected_third_version(tmp_path: Path) -> None:
    state, target, _, _ = _executing_state(tmp_path)
    external = b"value = 99\n"
    target.write_bytes(external)

    result = resume_edit_execution(
        task_id="task-001",
        action_id="action-001",
        state=state,
        next_task_status_id=lambda: "status-004",
    )

    assert result.status == "failed"
    assert result.error.code.value == "VERSION_MISMATCH"
    assert target.read_bytes() == external
    assert state.task_statuses.get_current("task-001").status is TaskStatus.RUNNING
