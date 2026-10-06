from pathlib import Path

import pytest

from forgemind.runtime.edit_file_handler import (
    EditFilePermissionWaitingResult,
    StaleEditFileDecisionError,
    handle_edit_file_decision,
)
from forgemind.schema.decisions import EditFileToolCallDecision
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _create_running_state(
    tmp_path: Path,
) -> tuple[SQLiteForgeMindState, TaskRecord, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    target = project_root / "app.py"
    target.write_text("discount = 1\n", encoding="utf-8")
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-edit-handler",
        original_request="把折扣修改为 2",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-edit-handler-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state, task, target


def _decision() -> EditFileToolCallDecision:
    return EditFileToolCallDecision(
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "app.py",
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": "sha256:observed-before-model-call",
        },
        reason="按用户要求修改折扣",
    )


def test_handler_persists_permission_waiting_without_editing_file(
    tmp_path: Path,
) -> None:
    state, task, target = _create_running_state(tmp_path)

    result = handle_edit_file_decision(
        _decision(),
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-edit-handler-1",
        next_permission_request_id=lambda: "permission-edit-handler-1",
        next_task_status_id=lambda: "status-edit-handler-2",
    )

    assert isinstance(result, EditFilePermissionWaitingResult)
    assert result.action.action_id == "action-edit-handler-1"
    assert result.permission_request.action_id == result.action.action_id
    assert result.waiting_status.status is TaskStatus.WAITING_USER
    assert target.read_text(encoding="utf-8") == "discount = 1\n"

    restored = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    assert restored.current_status == result.waiting_status
    assert restored.actions[0].action == result.action
    assert (
        restored.actions[0].permission_request
        == result.permission_request
    )
    assert restored.actions[0].permission_decision is None
    assert restored.actions[0].observation is None


def test_handler_rejects_edit_when_task_is_no_longer_running(
    tmp_path: Path,
) -> None:
    state, task, target = _create_running_state(tmp_path)
    state.task_statuses.record(
        TaskStatusRecord(
            task_status_id="status-edit-handler-2",
            task_id=task.task_id,
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="模型调用期间任务已转为等待用户",
        )
    )

    with pytest.raises(StaleEditFileDecisionError):
        handle_edit_file_decision(
            _decision(),
            task_id=task.task_id,
            state=state,
            next_action_id=lambda: "must-not-be-registered",
            next_permission_request_id=lambda: "must-not-be-created",
            next_task_status_id=lambda: "must-not-be-recorded",
        )

    assert state.get_task_view(task.task_id).actions == ()
    assert target.read_text(encoding="utf-8") == "discount = 1\n"
