"""把 Agent 的完成 Decision 转换为原子任务终态。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.acceptance import accept_complete_task_decision
from forgemind.runtime.ids import new_action_id, new_task_status_id
from forgemind.schema.actions import AcceptedCompletionAction
from forgemind.schema.decisions import CompleteTaskDecision
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


@dataclass(frozen=True, slots=True)
class CompletionResult:
    action: AcceptedCompletionAction
    completed_status: TaskStatusRecord


def complete_task(
    decision: CompleteTaskDecision,
    *,
    task_id: str,
    state: SQLiteForgeMindState,
    next_action_id: Callable[[], str] = new_action_id,
    next_task_status_id: Callable[[], str] = new_task_status_id,
) -> CompletionResult:
    current = state.task_statuses.get_current(task_id)
    action = accept_complete_task_decision(
        decision, task_id=task_id, next_action_id=next_action_id
    )
    completed = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.COMPLETED,
        reason=decision.summary,
    )
    state.record_task_completion(action, completed)
    return CompletionResult(action, completed)
