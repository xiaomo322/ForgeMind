from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.execution import EditExecutionPlan
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
    task = TaskRecord(
        task_id="task-001",
        original_request="修改文件",
        project_root=str(tmp_path.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-001",
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
            permission_request_id="request-001",
            task_id=action.task_id,
            action_id=action.action_id,
            status="pending",
            action_type="tool_call",
            tool_name="edit_file",
            arguments=action.arguments,
            reason="需要批准修改",
            basis_ids=("policy:edit",),
        ),
        TaskStatusRecord(
            task_status_id="status-002",
            task_id=task.task_id,
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="等待批准",
        ),
    )
    return state


def _action() -> AcceptedEditFileToolAction:
    return AcceptedEditFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "app.py",
            "old_text": "old",
            "new_text": "new",
            "expected_version": "sha256:before",
        },
        reason="修改文件",
    )


def _decision() -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        permission_decision_id="decision-001",
        permission_request_id="request-001",
        task_id="task-001",
        action_id="action-001",
        decision=PermissionDecision.APPROVE,
        source="user",
        raw_response="同意",
    )


def _plan() -> EditExecutionPlan:
    return EditExecutionPlan(
        action_id="action-001",
        task_id="task-001",
        path="app.py",
        before_version="sha256:before",
        after_version="sha256:after",
        diff="--- app.py\n+++ app.py\n@@\n-old\n+new\n",
    )


def _executing(status_id: str = "status-003") -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=status_id,
        task_id="task-001",
        revision=3,
        status=TaskStatus.EXECUTING,
        reason="已批准，正在执行修改",
    )


def test_approval_plan_and_executing_status_are_atomic(tmp_path: Path) -> None:
    state = _waiting_state(tmp_path)

    state.record_permission_approval_executing(
        _decision(), _plan(), _executing()
    )

    reopened = SQLiteForgeMindState.open(state.database_path)
    assert reopened.permission_decisions.get("decision-001") == _decision()
    assert reopened.edit_execution_plans.get("action-001") == _plan()
    assert reopened.task_statuses.get_current("task-001") == _executing()


def test_status_conflict_rolls_back_approval_and_plan(tmp_path: Path) -> None:
    state = _waiting_state(tmp_path)

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_permission_approval_executing(
            _decision(), _plan(), _executing("status-002")
        )

    with pytest.raises(KeyError):
        state.permission_decisions.get("decision-001")
    with pytest.raises(KeyError):
        state.edit_execution_plans.get("action-001")
    assert state.task_statuses.get_current("task-001").status is TaskStatus.WAITING_USER
