"""验证 read_file Decision 的 SQLite 应用级处理器。"""

from pathlib import Path

import pytest

from forgemind.runtime.read_file_handler import (
    StaleReadFileDecisionError,
    handle_read_file_decision,
)
from forgemind.schema.decisions import ReadFileToolCallDecision
from forgemind.schema.observations import ReadFileSuccessObservation
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _create_running_state(
    tmp_path: Path,
) -> tuple[SQLiteForgeMindState, TaskRecord]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text(
        "price = 100\ndiscount = 0.8\n",
        encoding="utf-8",
    )
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-read-handler",
        original_request="检查价格与折扣计算",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-read-handler-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state, task


def _decision() -> ReadFileToolCallDecision:
    return ReadFileToolCallDecision(
        action_type="tool_call",
        tool_name="read_file",
        arguments=ReadFileArguments(
            path="app.py",
            start_line=1,
            max_lines=1,
        ),
        reason="读取价格附近的第一段代码",
    )


def test_handler_persists_partial_read_observation(
    tmp_path: Path,
) -> None:
    state, task = _create_running_state(tmp_path)

    result = handle_read_file_decision(
        _decision(),
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-read-handler-1",
    )

    assert result.action.action_id == "action-read-handler-1"
    assert isinstance(result.observation, ReadFileSuccessObservation)
    assert result.observation.result.returned_lines == 1
    assert result.observation.result.eof is False
    reopened_view = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    assert reopened_view.actions[0].action == result.action
    assert reopened_view.actions[0].observation == result.observation


def test_handler_rejects_read_when_task_is_no_longer_running(
    tmp_path: Path,
) -> None:
    state, task = _create_running_state(tmp_path)
    state.task_statuses.record(
        TaskStatusRecord(
            task_status_id="status-read-handler-2",
            task_id=task.task_id,
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="模型调用期间任务转为等待用户",
        )
    )

    with pytest.raises(StaleReadFileDecisionError):
        handle_read_file_decision(
            _decision(),
            task_id=task.task_id,
            state=state,
            next_action_id=lambda: "must-not-be-registered",
        )

    assert state.get_task_view(task.task_id).actions == ()
