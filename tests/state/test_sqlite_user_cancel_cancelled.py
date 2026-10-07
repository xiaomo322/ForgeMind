from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.state.sqlite_task_status_registry import DuplicateTaskStatusIdError


def make_waiting_state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.sqlite3")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="等待期间允许用户取消",
            project_root=str(tmp_path.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="status-running-001",
            task_id="task-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务开始",
        ),
    )
    state.record_ask_user_waiting(
        AcceptedAskUserAction(
            action_id="action-question-001",
            task_id="task-001",
            action_type="ask_user",
            reason="缺少用户选择",
            question="是否继续？",
            options=("继续",),
        ),
        TaskStatusRecord(
            task_status_id="status-waiting-002",
            task_id="task-001",
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="等待用户回答",
        ),
    )
    return state


def make_cancel() -> UserResponseRecord:
    return UserResponseRecord(
        response_id="response-cancel-001",
        task_id="task-001",
        question_action_id="action-question-001",
        response_type=UserResponseType.CANCEL,
        raw_response="先取消这个任务",
        selected_option=None,
        cancellation_reason="用户暂时不继续",
    )


def make_cancelled_status(
    status_id: str = "status-cancelled-003",
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=status_id,
        task_id="task-001",
        revision=3,
        status=TaskStatus.CANCELLED,
        reason="用户明确取消任务",
    )


def test_cancel_and_cancelled_status_survive_restart(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)
    cancel = make_cancel()
    cancelled_status = make_cancelled_status()

    state.record_user_cancel_cancelled(cancel, cancelled_status)
    reopened = SQLiteForgeMindState.open(state.database_path)

    assert reopened.user_responses.get(cancel.response_id) == cancel
    assert reopened.task_statuses.get_current("task-001") == cancelled_status
    assert reopened.get_task_view("task-001").actions[0].user_response == cancel


def test_status_conflict_rolls_back_cancel_response(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)
    cancel = make_cancel()

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_user_cancel_cancelled(
            cancel,
            make_cancelled_status("status-waiting-002"),
        )

    with pytest.raises(KeyError):
        state.user_responses.get(cancel.response_id)
    assert (
        state.task_statuses.get_current("task-001").status
        is TaskStatus.WAITING_USER
    )
