from pathlib import Path

import pytest

from forgemind.runtime.task_status import (
    InvalidTaskStatusTransitionError,
    transition_task_status,
)
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _state_with_running_task(
    tmp_path: Path,
) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-001",
        original_request="修复会员折扣没有生效的问题",
        project_root=str(tmp_path.resolve()),
    )
    initial = TaskStatusRecord(
        task_status_id="status-001",
        task_id=task.task_id,
        revision=1,
        status=TaskStatus.RUNNING,
        reason="任务创建",
    )
    state.create_task(task, initial)
    return state


def test_runtime_assigns_next_status_revision_and_registers_it(
    tmp_path: Path,
) -> None:
    state = _state_with_running_task(tmp_path)

    waiting = transition_task_status(
        "task-001",
        TaskStatus.WAITING_USER,
        "等待用户批准命令",
        statuses=state.task_statuses,
        next_task_status_id=lambda: "status-002",
    )

    assert waiting == TaskStatusRecord(
        task_status_id="status-002",
        task_id="task-001",
        revision=2,
        status=TaskStatus.WAITING_USER,
        reason="等待用户批准命令",
    )
    assert state.task_statuses.get_current("task-001") == waiting


def test_runtime_does_not_register_invalid_transition(
    tmp_path: Path,
) -> None:
    state = _state_with_running_task(tmp_path)
    transition_task_status(
        "task-001",
        TaskStatus.WAITING_USER,
        "等待用户回答",
        statuses=state.task_statuses,
        next_task_status_id=lambda: "status-002",
    )

    with pytest.raises(InvalidTaskStatusTransitionError):
        transition_task_status(
            "task-001",
            TaskStatus.COMPLETED,
            "错误地跳过恢复执行",
            statuses=state.task_statuses,
            next_task_status_id=lambda: "status-003",
        )

    current = state.task_statuses.get_current("task-001")
    assert current.task_status_id == "status-002"
    assert current.revision == 2
