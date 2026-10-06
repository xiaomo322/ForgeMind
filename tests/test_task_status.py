import pytest
from pydantic import ValidationError

from forgemind.runtime.task_status import (
    InvalidTaskStatusTransitionError,
    require_task_status_transition,
)
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord


def test_task_status_record_requires_positive_revision() -> None:
    with pytest.raises(ValidationError):
        TaskStatusRecord(
            task_status_id="status-001",
            task_id="task-001",
            revision=0,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.RUNNING, TaskStatus.WAITING_USER),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.BLOCKED),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
        (TaskStatus.WAITING_USER, TaskStatus.RUNNING),
        (TaskStatus.WAITING_USER, TaskStatus.EXECUTING),
        (TaskStatus.EXECUTING, TaskStatus.RUNNING),
        (TaskStatus.WAITING_USER, TaskStatus.BLOCKED),
        (TaskStatus.WAITING_USER, TaskStatus.CANCELLED),
        (TaskStatus.EXECUTING, TaskStatus.BLOCKED),
        (TaskStatus.EXECUTING, TaskStatus.CANCELLED),
    ],
)
def test_allowed_task_status_transitions_do_not_raise(
    current: TaskStatus,
    target: TaskStatus,
) -> None:
    require_task_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.RUNNING, TaskStatus.RUNNING),
        (TaskStatus.WAITING_USER, TaskStatus.WAITING_USER),
        (TaskStatus.WAITING_USER, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.EXECUTING),
        (TaskStatus.EXECUTING, TaskStatus.EXECUTING),
        (TaskStatus.EXECUTING, TaskStatus.COMPLETED),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.BLOCKED, TaskStatus.RUNNING),
        (TaskStatus.CANCELLED, TaskStatus.RUNNING),
    ],
)
def test_invalid_task_status_transitions_are_rejected(
    current: TaskStatus,
    target: TaskStatus,
) -> None:
    with pytest.raises(InvalidTaskStatusTransitionError) as caught:
        require_task_status_transition(current, target)

    assert caught.value.current is current
    assert caught.value.target is target
