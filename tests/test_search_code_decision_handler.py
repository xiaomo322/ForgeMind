"""验证 search_code Decision 的 SQLite 应用级处理器。"""

from pathlib import Path

import pytest

from forgemind.runtime.search_code_handler import (
    StaleSearchCodeDecisionError,
    handle_search_code_decision,
)
from forgemind.schema.decisions import SearchCodeToolCallDecision
from forgemind.schema.observations import SearchCodeSuccessObservation
from forgemind.schema.search_code import SearchCodeArguments
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _create_running_state(
    tmp_path: Path,
) -> tuple[SQLiteForgeMindState, TaskRecord]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text(
        "class ForgeMind:\n    pass\n",
        encoding="utf-8",
    )
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-search-handler",
        original_request="检查 ForgeMind 项目",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-search-handler-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state, task


def _decision() -> SearchCodeToolCallDecision:
    return SearchCodeToolCallDecision(
        action_type="tool_call",
        tool_name="search_code",
        arguments=SearchCodeArguments(
            query="ForgeMind",
            scope=".",
            max_results=20,
        ),
        reason="先定位相关代码",
    )


def test_handler_persists_action_and_success_observation(
    tmp_path: Path,
) -> None:
    state, task = _create_running_state(tmp_path)

    result = handle_search_code_decision(
        _decision(),
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-search-handler-1",
    )

    assert result.action.action_id == "action-search-handler-1"
    assert isinstance(result.observation, SearchCodeSuccessObservation)
    assert result.observation.action_id == result.action.action_id
    reopened_view = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    assert reopened_view.actions[0].action == result.action
    assert reopened_view.actions[0].observation == result.observation


def test_handler_rejects_decision_when_task_is_no_longer_running(
    tmp_path: Path,
) -> None:
    state, task = _create_running_state(tmp_path)
    state.task_statuses.record(
        TaskStatusRecord(
            task_status_id="status-search-handler-2",
            task_id=task.task_id,
            revision=2,
            status=TaskStatus.WAITING_USER,
            reason="模型调用期间任务转为等待用户",
        )
    )

    with pytest.raises(StaleSearchCodeDecisionError):
        handle_search_code_decision(
            _decision(),
            task_id=task.task_id,
            state=state,
            next_action_id=lambda: "must-not-be-registered",
        )

    assert state.get_task_view(task.task_id).actions == ()
