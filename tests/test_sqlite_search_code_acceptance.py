"""验证 Action 接受逻辑可复用于 SQLite Registry。"""

from pathlib import Path

from forgemind.runtime.acceptance import (
    accept_and_register_search_code_decision,
)
from forgemind.schema.decisions import SearchCodeToolCallDecision
from forgemind.schema.search_code import SearchCodeArguments
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_search_code_decision_is_persisted_by_sqlite_registry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    project_root = tmp_path / "project"
    project_root.mkdir()
    state = SQLiteForgeMindState.open(database_path)
    task = TaskRecord(
        task_id="task-search-sqlite",
        original_request="检查 ForgeMind 项目",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-search-sqlite-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    decision = SearchCodeToolCallDecision(
        action_type="tool_call",
        tool_name="search_code",
        arguments=SearchCodeArguments(
            query="ForgeMind",
            scope=".",
            max_results=20,
        ),
        reason="先检查项目源码",
    )

    action = accept_and_register_search_code_decision(
        decision,
        task_id=task.task_id,
        registry=state.actions,
        next_action_id=lambda: "action-search-sqlite-1",
    )

    reopened = SQLiteForgeMindState.open(database_path)
    assert reopened.actions.get(action.action_id) == action
