import json
from pathlib import Path

from forgemind.agent.decision_parser import parse_agent_decision
from forgemind.runtime.completion import complete_task
from forgemind.runtime.decision_dispatch import (
    AgentDecisionHandlers,
    dispatch_agent_decision,
)
from forgemind.schema.actions import AcceptedCompletionAction
from forgemind.schema.decisions import CompleteTaskDecision
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _state(tmp_path: Path) -> SQLiteForgeMindState:
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
    return state


def test_complete_decision_parses_and_dispatches() -> None:
    decision = parse_agent_decision(
        json.dumps(
            {
                "action_type": "complete",
                "reason": "目标已经完成",
                "summary": "已修复折扣并通过测试",
            },
            ensure_ascii=False,
        )
    )
    assert isinstance(decision, CompleteTaskDecision)
    calls: list[object] = []
    unexpected = lambda value: (_ for _ in ()).throw(AssertionError(value))
    handlers = AgentDecisionHandlers(
        ask_user=unexpected,
        read_file=unexpected,
        search_code=unexpected,
        edit_file=unexpected,
        run_tests=unexpected,
        run_command=unexpected,
        complete=lambda value: calls.append(value) or "completed",
    )

    assert dispatch_agent_decision(decision, handlers=handlers) == "completed"
    assert calls == [decision]


def test_completion_action_and_status_survive_restart(tmp_path: Path) -> None:
    state = _state(tmp_path)
    result = complete_task(
        CompleteTaskDecision(
            action_type="complete",
            reason="目标已经完成",
            summary="没有待处理行动",
        ),
        task_id="task-001",
        state=state,
        next_action_id=lambda: "action-complete-001",
        next_task_status_id=lambda: "status-002",
    )

    reopened = SQLiteForgeMindState.open(state.database_path)
    view = reopened.get_task_view("task-001")
    assert isinstance(result.action, AcceptedCompletionAction)
    assert view.actions[-1].action == result.action
    assert view.actions[-1].observation is None
    assert view.current_status.status is TaskStatus.COMPLETED
