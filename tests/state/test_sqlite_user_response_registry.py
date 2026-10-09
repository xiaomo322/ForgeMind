from pathlib import Path

import pytest

from forgemind.runtime.user_responses import UserResponseQuestionMismatchError
from forgemind.schema.actions import (
    AcceptedAskUserAction,
    AcceptedReadFileToolAction,
)
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.state.sqlite_user_response_registry import (
    SQLiteUserResponseRegistry,
)
from forgemind.state.user_response_registry import (
    DuplicateQuestionResponseError,
    DuplicateUserResponseIdError,
    QuestionActionTypeError,
    UnknownQuestionActionIdError,
)


def create_task(state: SQLiteForgeMindState, project_root: Path) -> None:
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="验证用户回答持久化",
            project_root=str(project_root.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="task-status-001",
            task_id="task-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务开始",
        ),
    )


def make_question(action_id: str = "action-question-001") -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id=action_id,
        task_id="task-001",
        action_type="ask_user",
        reason="需要用户决定",
        question="请选择方案。",
        options=("A", "B"),
    )


def make_response(
    *,
    response_id: str = "response-001",
    question_action_id: str = "action-question-001",
    task_id: str = "task-001",
    selected_option: str = "A",
) -> UserResponseRecord:
    return UserResponseRecord(
        response_id=response_id,
        task_id=task_id,
        question_action_id=question_action_id,
        response_type=UserResponseType.ANSWER,
        raw_response=f"选 {selected_option}",
        selected_option=selected_option,
        cancellation_reason=None,
    )


def open_registry(
    database_path: Path,
) -> tuple[SQLiteForgeMindState, SQLiteUserResponseRegistry]:
    state = SQLiteForgeMindState.open(database_path)
    return state, SQLiteUserResponseRegistry(database_path, state.actions)


def test_response_survives_registry_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    state, responses = open_registry(database_path)
    create_task(state, tmp_path / "workspace")
    state.actions.register(make_question())
    response = make_response()

    responses.record(response)
    _, reopened = open_registry(database_path)

    assert reopened.get("response-001") == response
    assert reopened.get_for_question("action-question-001") == response


def test_unknown_question_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    state, responses = open_registry(database_path)
    create_task(state, tmp_path / "workspace")

    with pytest.raises(UnknownQuestionActionIdError):
        responses.record(make_response())


def test_tool_action_cannot_be_answered(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    state, responses = open_registry(database_path)
    create_task(state, tmp_path / "workspace")
    state.actions.register(
        AcceptedReadFileToolAction(
            action_id="action-question-001",
            task_id="task-001",
            action_type="tool_call",
            tool_name="read_file",
            arguments={"path": "src/app.py"},
            reason="读取代码",
        )
    )

    with pytest.raises(QuestionActionTypeError):
        responses.record(make_response())


def test_question_link_mismatch_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    state, responses = open_registry(database_path)
    create_task(state, tmp_path / "workspace")
    state.actions.register(make_question())

    with pytest.raises(UserResponseQuestionMismatchError):
        responses.record(make_response(task_id="task-other"))


def test_duplicate_response_id_does_not_overwrite_disk_record(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    state, responses = open_registry(database_path)
    create_task(state, tmp_path / "workspace")
    state.actions.register(make_question())
    state.actions.register(make_question("action-question-002"))
    original = make_response()
    duplicate = make_response(
        question_action_id="action-question-002",
        selected_option="B",
    )

    responses.record(original)
    with pytest.raises(DuplicateUserResponseIdError):
        responses.record(duplicate)

    assert responses.get("response-001") == original


def test_second_response_for_same_question_does_not_overwrite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    state, responses = open_registry(database_path)
    create_task(state, tmp_path / "workspace")
    state.actions.register(make_question())
    original = make_response()
    second = make_response(response_id="response-002", selected_option="B")

    responses.record(original)
    with pytest.raises(DuplicateQuestionResponseError):
        responses.record(second)

    assert responses.get_for_question("action-question-001") == original
    with pytest.raises(KeyError):
        responses.get("response-002")
