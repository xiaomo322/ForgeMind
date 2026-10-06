from functools import partial
from pathlib import Path
from typing import NoReturn

from forgemind.agent.loop import run_agent_loop_step
from forgemind.runtime.decision_dispatch import AgentDecisionHandlers
from forgemind.runtime.edit_file_handler import (
    EditFilePermissionWaitingResult,
    handle_edit_file_decision,
)
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


class EditFileModel:
    """返回固定 edit_file JSON，模拟真实模型供应商响应。"""

    def generate(self, turn_input: AgentTurnInput) -> str:
        assert turn_input.messages[0].role == "system"
        assert turn_input.messages[1].role == "user"
        return (
            '{"action_type":"tool_call","tool_name":"edit_file",'
            '"arguments":{"path":"app.py",'
            '"old_text":"discount = 1","new_text":"discount = 2",'
            '"expected_version":"sha256:observed-before-model-call"},'
            '"reason":"按用户要求修改折扣"}'
        )


def _unexpected_handler(decision: object) -> NoReturn:
    raise AssertionError(f"错误路由到 {type(decision).__name__}")


def test_agent_loop_pauses_edit_before_file_change(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    target = project_root / "app.py"
    target.write_text("discount = 1\n", encoding="utf-8")
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-edit-loop",
        original_request="把折扣修改为 2",
        project_root=str(project_root.resolve()),
    )
    state.create_task(
        task,
        TaskStatusRecord(
            task_status_id="status-edit-loop-1",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )

    # 第一步：使用 partial 预先绑定 task_id、state 和三个确定性编号，
    # 得到只接收一个 EditFileToolCallDecision 的 edit_handler。
    edit_handler = partial(
        handle_edit_file_decision,
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-edit-loop-1",
        next_permission_request_id=lambda: "permission-edit-loop-1",
        next_task_status_id=lambda: "status-edit-loop-2",
    )

    # 第二步：创建 AgentDecisionHandlers。edit_file 使用 edit_handler，
    # 其余五个分支都使用 _unexpected_handler。
    handlers = AgentDecisionHandlers[EditFilePermissionWaitingResult](
        ask_user=_unexpected_handler,
        read_file=_unexpected_handler,
        search_code=_unexpected_handler,
        edit_file=edit_handler,
        run_tests=_unexpected_handler,
        run_command=_unexpected_handler,
    )

    # 第三步：调用 run_agent_loop_step，传入 task、state、EditFileModel、
    # handlers 和 max_action_count=20，保存返回值 result。
    result = run_agent_loop_step(
        task_id=task.task_id,
        state=state,
        model=EditFileModel(),
        handlers=handlers,
        max_action_count=20,
    )

    # 第四步：断言 dispatch_result 是 EditFilePermissionWaitingResult；
    # 再从 SQLite 重建视图，检查状态为 WAITING_USER、存在权限请求、
    # 没有 Observation，并检查 target 文件仍是原内容。
    assert isinstance(
        result.dispatch_result,
        EditFilePermissionWaitingResult,
    )

    restored = SQLiteForgeMindState.open(
        state.database_path
    ).get_task_view(task.task_id)
    assert restored.current_status.status is TaskStatus.WAITING_USER
    assert len(restored.actions) == 1

    action_state = restored.actions[0]
    assert action_state.permission_request is not None
    assert action_state.permission_decision is None
    assert action_state.observation is None
    assert target.read_text(encoding="utf-8") == "discount = 1\n"
