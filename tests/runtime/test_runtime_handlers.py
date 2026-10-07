from pathlib import Path

from forgemind.runtime.decision_dispatch import dispatch_agent_decision
from forgemind.runtime.handlers import build_runtime_handlers
from forgemind.schema.decisions import CompleteTaskDecision
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_runtime_handlers_include_completion_route(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="完成任务",
            project_root=str(tmp_path.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="status-001",
            task_id="task-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )

    result = dispatch_agent_decision(
        CompleteTaskDecision(
            action_type="complete",
            reason="目标完成",
            summary="没有待处理工作",
        ),
        handlers=build_runtime_handlers(task_id="task-001", state=state),
    )

    assert result.completed_status.status is TaskStatus.COMPLETED
