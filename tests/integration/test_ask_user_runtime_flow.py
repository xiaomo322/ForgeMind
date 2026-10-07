from pathlib import Path

from forgemind.runtime.ask_user import (
    AskUserWaitingResult,
    accept_ask_user_and_wait,
)
from forgemind.schema.decisions import AskUserDecision
from forgemind.schema.tasks import (
    TaskRecord,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_runtime_accepts_ask_user_and_pauses_task_atomically(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    state = SQLiteForgeMindState.open(database_path)
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
    decision = AskUserDecision(
        action_type="ask_user",
        reason="项目中没有折扣叠加规则",
        question="会员折扣和优惠券可以同时使用吗？",
        options=("可以", "不可以"),
    )

    result = accept_ask_user_and_wait(
        decision,
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-ask-001",
        next_task_status_id=lambda: "status-waiting-002",
    )

    assert type(result) is AskUserWaitingResult
    assert result.action.action_id == "action-ask-001"
    assert result.action.question == decision.question
    assert result.waiting_status == TaskStatusRecord(
        task_status_id="status-waiting-002",
        task_id=task.task_id,
        revision=2,
        status=TaskStatus.WAITING_USER,
        reason=decision.reason,
    )

    restored = SQLiteForgeMindState.open(database_path).get_task_view(
        task.task_id
    )
    assert restored.current_status == result.waiting_status
    assert restored.actions[0].action == result.action
    assert restored.actions[0].permission_request is None
    assert restored.actions[0].observation is None
