from pathlib import Path

from forgemind.runtime.ask_user import accept_ask_user_and_wait
from forgemind.runtime.user_answers import (
    UserAnswerRunningResult,
    resume_from_user_answer,
)
from forgemind.schema.decisions import AskUserDecision
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_user_answer_resumes_waiting_task_with_authoritative_records(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    state = SQLiteForgeMindState.open(database_path)
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="让 Agent 询问并根据用户回答继续",
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
            reason="需要选择数据库",
            question="请选择 SQLite 或 PostgreSQL。",
            options=("SQLite", "PostgreSQL"),
        ),
        task_id="task-001",
        state=state,
        next_action_id=lambda: "action-question-001",
        next_task_status_id=lambda: "status-waiting-002",
    )

    result = resume_from_user_answer(
        task_id="task-001",
        question_action_id=waiting.action.action_id,
        raw_response="使用 SQLite",
        selected_option="SQLite",
        state=state,
        next_response_id=lambda: "response-001",
        next_task_status_id=lambda: "status-running-003",
    )

    assert result == UserAnswerRunningResult(
        response=UserResponseRecord(
            response_id="response-001",
            task_id="task-001",
            question_action_id="action-question-001",
            response_type=UserResponseType.ANSWER,
            raw_response="使用 SQLite",
            selected_option="SQLite",
            cancellation_reason=None,
        ),
        running_status=TaskStatusRecord(
            task_status_id="status-running-003",
            task_id="task-001",
            revision=3,
            status=TaskStatus.RUNNING,
            reason="已收到有效用户回答",
        ),
    )

    reopened = SQLiteForgeMindState.open(database_path)
    assert reopened.user_responses.get("response-001") == result.response
    assert reopened.task_statuses.get_current("task-001") == result.running_status
