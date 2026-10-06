"""执行用户已批准的 run_tests 与 run_command 权威 Action。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.ids import new_permission_decision_id, new_task_status_id
from forgemind.runtime.run_command_execution import execute_run_command_action
from forgemind.runtime.run_tests_execution import execute_run_tests_action
from forgemind.schema.actions import (
    AcceptedRunCommandToolAction,
    AcceptedRunTestsToolAction,
)
from forgemind.schema.observations import TerminalObservation
from forgemind.schema.permissions import PermissionDecision, PermissionDecisionRecord
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


IdFactory = Callable[[], str]


class _ObservationCapture:
    """让现有执行模块生成 Observation，但把最终持久化交给外层事务。"""

    def __init__(self) -> None:
        self.value: TerminalObservation | None = None

    def record(self, observation: TerminalObservation) -> None:
        if self.value is not None:
            raise RuntimeError("一次 Tool 执行只能产生一个终态 Observation")
        self.value = observation


@dataclass(frozen=True, slots=True)
class ProcessPermissionExecutionResult:
    decision: PermissionDecisionRecord
    observation: TerminalObservation
    running_status: TaskStatusRecord


def approve_process_permission(
    *,
    task_id: str,
    permission_request_id: str,
    raw_response: str,
    state: SQLiteForgeMindState,
    allowed_programs: Mapping[str, Path],
    next_permission_decision_id: IdFactory = new_permission_decision_id,
    next_executing_status_id: IdFactory = new_task_status_id,
    next_running_status_id: IdFactory = new_task_status_id,
) -> ProcessPermissionExecutionResult:
    current = state.task_statuses.get_current(task_id)
    request = state.permission_requests.get(permission_request_id)
    action = state.actions.get(request.action_id)
    if current.status is not TaskStatus.WAITING_USER or action.task_id != task_id:
        raise RuntimeError("权限请求不是当前任务正在等待的 Action")

    decision = PermissionDecisionRecord(
        permission_decision_id=next_permission_decision_id(),
        permission_request_id=permission_request_id,
        task_id=task_id,
        action_id=action.action_id,
        decision=PermissionDecision.APPROVE,
        source="user",
        raw_response=raw_response,
    )
    executing = TaskStatusRecord(
        task_status_id=next_executing_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.EXECUTING,
        reason=f"用户已批准 {request.tool_name}，开始执行",
    )
    state.record_process_permission_approval_executing(decision, executing)

    capture = _ObservationCapture()
    project_root = Path(state.tasks.get(task_id).project_root)
    if isinstance(action, AcceptedRunTestsToolAction):
        observation = execute_run_tests_action(
            action, project_root=project_root, observations=capture
        )
    elif isinstance(action, AcceptedRunCommandToolAction):
        observation = execute_run_command_action(
            action,
            project_root=project_root,
            allowed_programs=allowed_programs,
            observations=capture,
        )
    else:
        raise TypeError("该批准入口只支持 run_tests 和 run_command")
    if capture.value != observation:
        raise RuntimeError("执行模块没有登记其返回的终态 Observation")

    running = TaskStatusRecord(
        task_status_id=next_running_status_id(),
        task_id=task_id,
        revision=executing.revision + 1,
        status=TaskStatus.RUNNING,
        reason=f"{request.tool_name} 已产生终态：{observation.status}",
    )
    state.record_execution_result_running(observation, running)
    return ProcessPermissionExecutionResult(decision, observation, running)
