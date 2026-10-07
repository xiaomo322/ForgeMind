from pathlib import Path

import pytest

from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.tasks import (
    TaskRecord,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_state import (
    AskUserWaitingTaskMismatchError,
    InvalidAskUserWaitingStatusError,
    SQLiteForgeMindState,
)
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
)


def _state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-ask-001",
        original_request="修复折扣规则",
        project_root=str(tmp_path.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-running-001",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state


def _action() -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id="action-ask-001",
        task_id="task-ask-001",
        action_type="ask_user",
        reason="缺少业务规则",
        question="折扣可以叠加吗？",
    )


def _waiting(
    task_status_id: str = "status-waiting-002",
) -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id=task_status_id,
        task_id="task-ask-001",
        revision=2,
        status=TaskStatus.WAITING_USER,
        reason="等待用户确认折扣规则",
    )


def test_ask_user_action_and_waiting_status_are_recorded_atomically(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    state.record_ask_user_waiting(_action(), _waiting())

    restored = SQLiteForgeMindState.open(
        tmp_path / "state.db"
    ).get_task_view("task-ask-001")
    assert restored.current_status == _waiting()
    assert restored.actions[0].action == _action()


def test_status_conflict_rolls_back_ask_user_action(tmp_path: Path) -> None:
    state = _state(tmp_path)
    conflicting_id = "status-running-001"

    with pytest.raises(DuplicateTaskStatusIdError):
        state.record_ask_user_waiting(
            _action(),
            _waiting(task_status_id=conflicting_id),
        )

    with pytest.raises(KeyError):
        state.actions.get(_action().action_id)
    assert state.task_statuses.get_current("task-ask-001").status is (
        TaskStatus.RUNNING
    )


def test_ask_user_waiting_requires_same_task(tmp_path: Path) -> None:
    state = _state(tmp_path)
    wrong_status = _waiting().model_copy(
        update={"task_id": "task-other"}
    )

    with pytest.raises(AskUserWaitingTaskMismatchError):
        state.record_ask_user_waiting(_action(), wrong_status)


def test_ask_user_waiting_requires_waiting_user_status(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    wrong_status = _waiting().model_copy(
        update={"status": TaskStatus.COMPLETED}
    )

    with pytest.raises(InvalidAskUserWaitingStatusError):
        state.record_ask_user_waiting(_action(), wrong_status)
