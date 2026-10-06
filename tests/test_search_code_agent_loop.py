"""验证 search_code 从模型 JSON 到 SQLite Observation 的单轮闭环。"""

from functools import partial
from pathlib import Path
from typing import NoReturn

from forgemind.agent.loop import run_agent_loop_step
from forgemind.runtime.decision_dispatch import AgentDecisionHandlers
from forgemind.runtime.search_code_handler import (
    SearchCodeHandlingResult,
    handle_search_code_decision,
)
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.observations import SearchCodeSuccessObservation
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


class SearchCodeModel:
    """返回一条固定 search_code JSON，模拟真实供应商响应。"""

    def generate(self, turn_input: AgentTurnInput) -> str:
        assert turn_input.messages[0].role == "system"
        assert turn_input.messages[1].role == "user"
        return (
            '{"action_type":"tool_call","tool_name":"search_code",'
            '"arguments":{"query":"ForgeMind","scope":".",'
            '"max_results":20},"reason":"先定位相关代码"}'
        )


def _unexpected_handler(decision: object) -> NoReturn:
    raise AssertionError(f"错误路由到 {type(decision).__name__}")


def test_agent_loop_dispatches_search_code_and_records_result(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text(
        "class ForgeMind:\n    pass\n",
        encoding="utf-8",
    )
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-search-loop",
        original_request="定位 ForgeMind 的实现",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-search-loop-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    search_handler = partial(
        handle_search_code_decision,
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-search-loop-1",
    )
    handlers = AgentDecisionHandlers[SearchCodeHandlingResult](
        ask_user=_unexpected_handler,
        read_file=_unexpected_handler,
        search_code=search_handler,
        edit_file=_unexpected_handler,
        run_tests=_unexpected_handler,
        run_command=_unexpected_handler,
    )

    result = run_agent_loop_step(
        task_id=task.task_id,
        state=state,
        model=SearchCodeModel(),
        handlers=handlers,
        max_action_count=20,
    )

    assert isinstance(result.dispatch_result, SearchCodeHandlingResult)
    assert isinstance(
        result.dispatch_result.observation,
        SearchCodeSuccessObservation,
    )
    restored = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    assert len(restored.actions) == 1
    assert restored.actions[0].observation == (
        result.dispatch_result.observation
    )
