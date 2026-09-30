from pathlib import Path

from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_unified_state_restores_user_response_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    state = SQLiteForgeMindState.open(database_path)
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="验证统一 State 中的用户回答",
            project_root=str(tmp_path.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="task-status-001",
            task_id="task-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务开始",
        ),
    )
    question = AcceptedAskUserAction(
        action_id="action-question-001",
        task_id="task-001",
        action_type="ask_user",
        reason="需要用户决定",
        question="请选择方案。",
        options=("A", "B"),
    )
    state.actions.register(question)
    response = UserResponseRecord(
        response_id="response-001",
        task_id="task-001",
        question_action_id="action-question-001",
        response_type=UserResponseType.ANSWER,
        raw_response="选 A",
        selected_option="A",
        cancellation_reason=None,
    )

    state.user_responses.record(response)
    reopened = SQLiteForgeMindState.open(database_path)

    assert reopened.user_responses.get("response-001") == response
    assert (
        reopened.user_responses.get_for_question("action-question-001")
        == response
    )
