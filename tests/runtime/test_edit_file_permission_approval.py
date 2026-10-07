from pathlib import Path

from forgemind.runtime.permission_approvals import approve_edit_file_permission
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.permissions import PendingEditFilePermissionRequest
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _waiting_state(tmp_path: Path) -> tuple[SQLiteForgeMindState, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    target = project_root / "app.py"
    before = b"price = 100\ndiscount = 1\n"
    target.write_bytes(before)
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="把折扣改成 2",
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
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": calculate_content_version(before),
        },
        reason="修复折扣",
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
    return state, target


def test_approved_edit_writes_file_and_records_authoritative_result(
    tmp_path: Path,
) -> None:
    state, target = _waiting_state(tmp_path)

    result = approve_edit_file_permission(
        task_id="task-001",
        permission_request_id="request-001",
        raw_response="同意修改",
        state=state,
        next_permission_decision_id=lambda: "decision-001",
        next_executing_status_id=lambda: "status-003",
        next_running_status_id=lambda: "status-004",
    )

    assert target.read_text(encoding="utf-8") == "price = 100\ndiscount = 2\n"
    assert result.observation.status == "success"
    view = SQLiteForgeMindState.open(state.database_path).get_task_view("task-001")
    assert view.current_status.status is TaskStatus.RUNNING
    assert view.current_status.revision == 4
    assert view.actions[0].permission_decision == result.decision
    assert view.actions[0].observation == result.observation
    assert state.edit_execution_plans.get("action-001") == result.plan
