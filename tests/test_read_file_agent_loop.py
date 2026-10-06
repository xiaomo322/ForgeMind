"""验证 read_file 从模型 JSON 到 SQLite Observation 的单轮闭环。"""

from functools import partial
from pathlib import Path
from typing import NoReturn

from forgemind.agent.loop import run_agent_loop_step
from forgemind.runtime.decision_dispatch import AgentDecisionHandlers
from forgemind.runtime.read_file_handler import (
    ReadFileHandlingResult,
    handle_read_file_decision,
)
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.observations import ReadFileSuccessObservation
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


class ReadFileModel:
    """返回固定的分段读取 JSON，模拟真实供应商响应。"""

    def generate(self, turn_input: AgentTurnInput) -> str:
        assert turn_input.messages[0].role == "system"
        assert turn_input.messages[1].role == "user"
        return (
            '{"action_type":"tool_call","tool_name":"read_file",'
            '"arguments":{"path":"app.py","start_line":1,'
            '"max_lines":1,"expected_version":null},'
            '"reason":"先读取价格附近的第一段代码"}'
        )


def _unexpected_handler(decision: object) -> NoReturn:
    raise AssertionError(f"错误路由到 {type(decision).__name__}")


def test_agent_loop_records_partial_read_with_eof_false(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text(
        "price = 100\ndiscount = 0.8\n",
        encoding="utf-8",
    )
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-read-loop",
        original_request="检查价格与折扣计算",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-read-loop-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    read_handler = partial(
        handle_read_file_decision,
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-read-loop-1",
    )
    handlers = AgentDecisionHandlers[ReadFileHandlingResult](
        ask_user=_unexpected_handler,
        read_file=read_handler,
        search_code=_unexpected_handler,
        edit_file=_unexpected_handler,
        run_tests=_unexpected_handler,
        run_command=_unexpected_handler,
    )

    result = run_agent_loop_step(
        task_id=task.task_id,
        state=state,
        model=ReadFileModel(),
        handlers=handlers,
        max_action_count=20,
    )

    assert isinstance(result.dispatch_result, ReadFileHandlingResult)
    observation = result.dispatch_result.observation
    assert isinstance(observation, ReadFileSuccessObservation)
    assert observation.result.content.splitlines() == ["price = 100"]
    assert observation.result.eof is False
    restored = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    restored_observation = restored.actions[0].observation
    assert isinstance(restored_observation, ReadFileSuccessObservation)
    assert restored_observation.result.eof is False
