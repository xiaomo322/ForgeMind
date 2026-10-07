from pathlib import Path

from forgemind.runtime.edit_file_handler import handle_edit_file_decision
from forgemind.runtime.permission_rejections import (
    PermissionRejectionRunningResult,
    reject_permission_request,
)
from forgemind.schema.decisions import EditFileToolCallDecision
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.permissions import PermissionDecision
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_user_rejection_records_fact_and_resumes_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    target = project_root / "app.py"
    target.write_text("discount = 1\n", encoding="utf-8")
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-rejection-handler",
        original_request="把折扣修改为 2",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-rejection-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    waiting = handle_edit_file_decision(
        EditFileToolCallDecision(
            action_type="tool_call",
            tool_name="edit_file",
            arguments={
                "path": "app.py",
                "old_text": "discount = 1",
                "new_text": "discount = 2",
                "expected_version": "sha256:observed-before-model-call",
            },
            reason="按用户要求修改折扣",
        ),
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-rejection-1",
        next_permission_request_id=lambda: "permission-rejection-1",
        next_task_status_id=lambda: "status-rejection-2",
    )

    result = reject_permission_request(
        task_id=task.task_id,
        permission_request_id=(
            waiting.permission_request.permission_request_id
        ),
        raw_response="不同意这次修改",
        state=state,
        next_permission_decision_id=lambda: "decision-rejection-1",
        next_task_status_id=lambda: "status-rejection-3",
    )

    assert isinstance(result, PermissionRejectionRunningResult)
    assert result.decision.decision is PermissionDecision.REJECT
    assert result.observation.status == "rejected"
    assert (
        result.observation.error.code
        is ObservationErrorCode.PERMISSION_DENIED
    )
    assert result.running_status.status is TaskStatus.RUNNING
    assert target.read_text(encoding="utf-8") == "discount = 1\n"

    restored = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    action_state = restored.actions[0]
    assert restored.current_status == result.running_status
    assert action_state.permission_decision == result.decision
    assert action_state.observation == result.observation
