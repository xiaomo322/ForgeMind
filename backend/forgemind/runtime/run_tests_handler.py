"""把 run_tests Decision 转换为持久化权限等待。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.acceptance import ActionIdFactory, accept_run_tests_decision
from forgemind.runtime.ids import new_action_id, new_permission_request_id, new_task_status_id
from forgemind.runtime.permission_policy import check_run_tests_permission
from forgemind.runtime.permissions import build_pending_run_tests_permission_request
from forgemind.schema.actions import AcceptedRunTestsToolAction
from forgemind.schema.decisions import RunTestsToolCallDecision
from forgemind.schema.permissions import PendingRunTestsPermissionRequest
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


@dataclass(frozen=True, slots=True)
class RunTestsPermissionWaitingResult:
    action: AcceptedRunTestsToolAction
    permission_request: PendingRunTestsPermissionRequest
    waiting_status: TaskStatusRecord


def handle_run_tests_decision(
    decision: RunTestsToolCallDecision,
    *,
    task_id: str,
    state: SQLiteForgeMindState,
    next_action_id: ActionIdFactory = new_action_id,
    next_permission_request_id: Callable[[], str] = new_permission_request_id,
    next_task_status_id: Callable[[], str] = new_task_status_id,
) -> RunTestsPermissionWaitingResult:
    current = state.task_statuses.get_current(task_id)
    if current.status is not TaskStatus.RUNNING:
        raise RuntimeError("只有 RUNNING 任务能接受 run_tests Decision")
    action = accept_run_tests_decision(
        decision, task_id=task_id, next_action_id=next_action_id
    )
    check = check_run_tests_permission(action)
    request = build_pending_run_tests_permission_request(
        action,
        check,
        next_permission_request_id=next_permission_request_id,
    )
    waiting = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.WAITING_USER,
        reason=check.reason,
    )
    state.record_tool_permission_waiting(action, request, waiting)
    return RunTestsPermissionWaitingResult(action, request, waiting)
