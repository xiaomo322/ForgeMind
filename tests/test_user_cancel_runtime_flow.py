from pathlib import Path

import pytest

from forgemind.runtime.ask_user import accept_ask_user_and_wait
from forgemind.runtime.task_status import (
    InvalidTaskStatusTransitionError,
    require_task_status_transition,
)
from forgemind.runtime.user_cancels import cancel_from_user_response
from forgemind.schema.decisions import AskUserDecision
from forgemind.schema.interactions import UserResponseType
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_user_cancel_terminates_waiting_task(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    state = SQLiteForgeMindState.open(database_path)
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="允许用户取消等待任务",
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
    waiting = accept_ask_user_and_wait(
        AskUserDecision(
            action_type="ask_user",
            reason="需要用户决定",
            question="是否继续？",
            options=("继续",),
        ),
        task_id="task-001",
        state=state,
        next_action_id=lambda: "action-question-001",
        next_task_status_id=lambda: "status-waiting-002",
    )

    result = cancel_from_user_response(
        task_id="task-001",
        question_action_id=waiting.action.action_id,
        raw_response="先取消，以后再处理",
        cancellation_reason="用户延后任务",
        state=state,
        next_response_id=lambda: "response-cancel-001",
        next_task_status_id=lambda: "status-cancelled-003",
    )

    assert result.response.response_type is UserResponseType.CANCEL
    assert result.response.raw_response == "先取消，以后再处理"
    assert result.cancelled_status.status is TaskStatus.CANCELLED

    reopened = SQLiteForgeMindState.open(database_path)
    assert reopened.user_responses.get("response-cancel-001") == result.response
    assert reopened.task_statuses.get_current("task-001") == result.cancelled_status

    with pytest.raises(InvalidTaskStatusTransitionError):
        require_task_status_transition(
            TaskStatus.CANCELLED,
            TaskStatus.RUNNING,
        )
