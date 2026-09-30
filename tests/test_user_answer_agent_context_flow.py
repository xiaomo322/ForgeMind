from pathlib import Path

from forgemind.context.builder import build_agent_task_context
from forgemind.context.messages import build_agent_turn_input
from forgemind.runtime.ask_user import accept_ask_user_and_wait
from forgemind.runtime.user_answers import resume_from_user_answer
from forgemind.schema.decisions import AskUserDecision
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_resumed_agent_context_contains_original_user_answer(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    state = SQLiteForgeMindState.open(database_path)
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="根据用户选择配置数据库",
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
            reason="缺少数据库选型",
            question="请选择 SQLite 或 PostgreSQL。",
            options=("SQLite", "PostgreSQL"),
        ),
        task_id="task-001",
        state=state,
        next_action_id=lambda: "action-question-001",
        next_task_status_id=lambda: "status-waiting-002",
    )
    resume_from_user_answer(
        task_id="task-001",
        question_action_id=waiting.action.action_id,
        raw_response="我想先用 SQLite",
        selected_option="SQLite",
        state=state,
        next_response_id=lambda: "response-001",
        next_task_status_id=lambda: "status-running-003",
    )

    reopened = SQLiteForgeMindState.open(database_path)
    task_view = reopened.get_task_view("task-001")
    context = build_agent_task_context(task_view, max_action_count=5)
    turn_input = build_agent_turn_input(context)

    question_state = task_view.actions[0]
    assert question_state.user_response is not None
    assert question_state.user_response.raw_response == "我想先用 SQLite"
    assert question_state.user_response.selected_option == "SQLite"

    user_message = turn_input.messages[1].content
    assert "请选择 SQLite 或 PostgreSQL" in user_message
    assert "我想先用 SQLite" in user_message
    assert '"selected_option": "SQLite"' in user_message
