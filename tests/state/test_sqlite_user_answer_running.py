from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import (
    InvalidUserAnswerRunningStatusError,
    InvalidUserAnswerTypeError,
    SQLiteForgeMindState,
    UserAnswerRequiresWaitingStatusError,
    UserAnswerStatusTaskMismatchError,
)
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
)
from forgemind.state.user_response_registry import (
    DuplicateQuestionResponseError,
)


def make_waiting_state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.sqlite3")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="等待用户选择后继续",
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
            question="请选择 A 或 B。",
            options=("A", "B"),
        ),
        TaskStatusRecord(
            task_status_id="status-waiting-002",
            task_id="task-001",
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="等待用户选择",
        ),
    )
    return state


def make_answer(
    *,
    response_id: str = "response-001",
    response_type: UserResponseType = UserResponseType.ANSWER,
) -> UserResponseRecord:
    return UserResponseRecord(
        response_id=response_id,
        task_id="task-001",
        question_action_id="action-question-001",
        response_type=response_type,
        raw_response="选 A" if response_type is UserResponseType.ANSWER else "取消",
        selected_option="A" if response_type is UserResponseType.ANSWER else None,
        cancellation_reason=None,
    )


def make_running_status(
    *,
    status_id: str = "status-running-003",
    task_id: str = "task-001",
    status: TaskStatus = TaskStatus.RUNNING,
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=status_id,
        task_id=task_id,
        revision=3,
        status=status,
        reason="已收到有效用户回答",
    )


def test_answer_and_running_status_survive_restart(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)
    answer = make_answer()
    running_status = make_running_status()

    state.record_user_answer_running(answer, running_status)
    reopened = SQLiteForgeMindState.open(state.database_path)

    assert reopened.user_responses.get(answer.response_id) == answer
    assert reopened.task_statuses.get_current("task-001") == running_status


def test_status_conflict_rolls_back_answer(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)
    answer = make_answer()
    duplicate_status = make_running_status(status_id="status-waiting-002")

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_user_answer_running(answer, duplicate_status)

    with pytest.raises(KeyError):
        state.user_responses.get(answer.response_id)
    assert (
        state.task_statuses.get_current("task-001").status
        is TaskStatus.WAITING_USER
    )


def test_existing_question_response_does_not_append_running_status(
    tmp_path: Path,
) -> None:
    state = make_waiting_state(tmp_path)
    existing = make_answer()
    state.user_responses.record(existing)

    with pytest.raises(DuplicateQuestionResponseError):
        state.record_user_answer_running(
            make_answer(response_id="response-002"),
            make_running_status(),
        )

    assert (
        state.task_statuses.get_current("task-001").status
        is TaskStatus.WAITING_USER
    )


def test_answer_requires_same_task_as_running_status(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)

    with pytest.raises(UserAnswerStatusTaskMismatchError):
        state.record_user_answer_running(
            make_answer(),
            make_running_status(task_id="task-other"),
        )


def test_cancel_is_not_accepted_by_answer_resume_flow(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)

    with pytest.raises(InvalidUserAnswerTypeError):
        state.record_user_answer_running(
            make_answer(response_type=UserResponseType.CANCEL),
            make_running_status(),
        )


def test_answer_requires_running_target(tmp_path: Path) -> None:
    state = make_waiting_state(tmp_path)

    with pytest.raises(InvalidUserAnswerRunningStatusError):
        state.record_user_answer_running(
            make_answer(),
            make_running_status(status=TaskStatus.CANCELLED),
        )


def test_answer_cannot_resume_task_that_is_not_waiting(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.sqlite3")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="尚未等待用户",
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
    state.actions.register(
        AcceptedAskUserAction(
            action_id="action-question-001",
            task_id="task-001",
            action_type="ask_user",
            reason="测试问题",
            question="请选择 A 或 B。",
            options=("A", "B"),
        )
    )

    with pytest.raises(UserAnswerRequiresWaitingStatusError):
        state.record_user_answer_running(
            make_answer(),
            TaskStatusRecord(
                task_status_id="status-running-002",
                task_id="task-001",
                revision=2,
                status=TaskStatus.RUNNING,
                reason="错误恢复",
            ),
        )
