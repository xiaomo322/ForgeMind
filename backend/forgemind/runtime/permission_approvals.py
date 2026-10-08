"""批准 edit_file 后执行、对账并恢复 Agent 循环。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.edit_file_execution import (
    build_edit_file_preparation_failure,
    build_edit_file_read_failure,
)
from forgemind.runtime.ids import (
    new_permission_decision_id,
    new_task_status_id,
)
from forgemind.runtime.project_paths import resolve_project_path
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.edit_file import EditFileResult
from forgemind.schema.execution import EditExecutionPlan
from forgemind.schema.observations import (
    EditFileSuccessObservation,
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    TerminalObservation,
)
from forgemind.schema.permissions import PermissionDecision, PermissionDecisionRecord
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.tools.edit_file import (
    EditFileVersionMismatchError,
    EditFileVersionChangedError,
    EditFileWriteError,
    EditTargetAmbiguousError,
    EditTargetNotFoundError,
    PreparedEdit,
    prepare_edit_from_snapshot,
    replace_file_atomically,
)
from forgemind.tools.read_file import ReadFileToolError, read_file_bytes


IdFactory = Callable[[], str]


class InvalidEditExecutionStateError(RuntimeError):
    """恢复请求与当前持久化执行状态不一致。"""


class CorruptEditExecutionPlanError(RuntimeError):
    """重新计算结果与写盘前持久化计划不一致。"""


@dataclass(frozen=True, slots=True)
class PermissionApprovalExecutionResult:
    """一次批准修改完成后产生的全部权威事实。"""

    decision: PermissionDecisionRecord
    plan: EditExecutionPlan | None
    observation: TerminalObservation
    running_status: TaskStatusRecord


def _success_from_plan(
    action: AcceptedEditFileToolAction,
    plan: EditExecutionPlan,
) -> EditFileSuccessObservation:
    return EditFileSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=EditFileResult(
            path=plan.path,
            before_version=plan.before_version,
            after_version=plan.after_version,
            replacement_count=1,
            diff=plan.diff,
        ),
    )


def _version_mismatch(
    action: AcceptedEditFileToolAction,
    plan: EditExecutionPlan,
    actual_version: str,
) -> FailedObservation:
    return FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(
            code=ObservationErrorCode.VERSION_MISMATCH,
            message="恢复执行时文件既不是修改前版本，也不是已写入版本",
            details=(
                ObservationErrorDetail(
                    key="before_version", value=plan.before_version
                ),
                ObservationErrorDetail(
                    key="after_version", value=plan.after_version
                ),
                ObservationErrorDetail(
                    key="actual_version", value=actual_version
                ),
            ),
        ),
    )


def _write_failure(
    action: AcceptedEditFileToolAction,
    failure: EditFileVersionChangedError | EditFileWriteError,
) -> FailedObservation:
    if isinstance(failure, EditFileVersionChangedError):
        code = ObservationErrorCode.VERSION_MISMATCH
        details = (
            ObservationErrorDetail(
                key="expected_version", value=failure.expected_version
            ),
            ObservationErrorDetail(
                key="actual_version", value=failure.actual_version
            ),
        )
        message = "写入前文件版本再次变化"
    else:
        code = ObservationErrorCode.FILE_WRITE_FAILED
        details = (
            ObservationErrorDetail(key="error_type", value=failure.error_type),
        )
        message = "操作系统未能写入文件"
    return FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(code=code, message=message, details=details),
    )


def resume_edit_execution(
    *,
    task_id: str,
    action_id: str,
    state: SQLiteForgeMindState,
    next_task_status_id: IdFactory = new_task_status_id,
) -> TerminalObservation:
    """根据当前文件版本安全完成或恢复一条已批准修改。"""

    current = state.task_statuses.get_current(task_id)
    if current.status is not TaskStatus.EXECUTING:
        raise InvalidEditExecutionStateError(task_id)
    action = state.actions.get(action_id)
    if not isinstance(action, AcceptedEditFileToolAction) or action.task_id != task_id:
        raise InvalidEditExecutionStateError(action_id)
    plan = state.edit_execution_plans.get(action_id)
    project_root = Path(state.tasks.get(task_id).project_root)
    resolved_path = resolve_project_path(project_root, plan.path)
    content = read_file_bytes(resolved_path)
    actual_version = calculate_content_version(content)

    if actual_version == plan.after_version:
        # 进程可能在 os.replace 成功后、写入 Observation 前崩溃。
        observation: TerminalObservation = _success_from_plan(action, plan)
    elif actual_version == plan.before_version:
        prepared = prepare_edit_from_snapshot(action, content=content)
        if (
            prepared.after_version != plan.after_version
            or prepared.diff != plan.diff
        ):
            raise CorruptEditExecutionPlanError(action_id)
        try:
            replace_file_atomically(resolved_path, prepared)
        except (EditFileVersionChangedError, EditFileWriteError) as failure:
            observation = _write_failure(action, failure)
        else:
            observation = _success_from_plan(action, plan)
    else:
        observation = _version_mismatch(action, plan, actual_version)

    running_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.RUNNING,
        reason=f"edit_file 已产生终态：{observation.status}",
    )
    state.record_execution_result_running(observation, running_status)
    return observation


def _record_preflight_failure(
    *,
    decision: PermissionDecisionRecord,
    observation: FailedObservation,
    current: TaskStatusRecord,
    state: SQLiteForgeMindState,
    next_running_status_id: IdFactory,
) -> PermissionApprovalExecutionResult:
    """批准已发生但尚未写盘时，把失败与恢复状态原子落库。"""

    running_status = TaskStatusRecord(
        task_status_id=next_running_status_id(),
        task_id=decision.task_id,
        revision=current.revision + 1,
        status=TaskStatus.RUNNING,
        reason=f"edit_file 执行前检查失败：{observation.error.code.value}",
    )
    state.record_permission_approval_failure_running(
        decision,
        observation,
        running_status,
    )
    return PermissionApprovalExecutionResult(
        decision=decision,
        plan=None,
        observation=observation,
        running_status=running_status,
    )


def approve_edit_file_permission(
    *,
    task_id: str,
    permission_request_id: str,
    raw_response: str,
    state: SQLiteForgeMindState,
    next_permission_decision_id: IdFactory = new_permission_decision_id,
    next_executing_status_id: IdFactory = new_task_status_id,
    next_running_status_id: IdFactory = new_task_status_id,
) -> PermissionApprovalExecutionResult:
    """批准一个待确认 edit_file，并完成可恢复的真实写入。"""

    current = state.task_statuses.get_current(task_id)
    request = state.permission_requests.get(permission_request_id)
    action = state.actions.get(request.action_id)
    if (
        current.status is not TaskStatus.WAITING_USER
        or not isinstance(action, AcceptedEditFileToolAction)
        or action.task_id != task_id
    ):
        raise InvalidEditExecutionStateError(permission_request_id)

    decision = PermissionDecisionRecord(
        permission_decision_id=next_permission_decision_id(),
        permission_request_id=permission_request_id,
        task_id=task_id,
        action_id=action.action_id,
        decision=PermissionDecision.APPROVE,
        source="user",
        raw_response=raw_response,
    )
    project_root = Path(state.tasks.get(task_id).project_root)
    resolved_path = resolve_project_path(project_root, action.arguments.path)
    try:
        content = read_file_bytes(resolved_path)
    except ReadFileToolError as failure:
        observation = build_edit_file_read_failure(
            action,
            failure,
            resolved_path=resolved_path,
        )
        return _record_preflight_failure(
            decision=decision,
            observation=observation,
            current=current,
            state=state,
            next_running_status_id=next_running_status_id,
        )
    try:
        prepared: PreparedEdit = prepare_edit_from_snapshot(
            action,
            content=content,
        )
    except (
        EditFileVersionMismatchError,
        UnicodeDecodeError,
        EditTargetNotFoundError,
        EditTargetAmbiguousError,
    ) as failure:
        observation = build_edit_file_preparation_failure(action, failure)
        return _record_preflight_failure(
            decision=decision,
            observation=observation,
            current=current,
            state=state,
            next_running_status_id=next_running_status_id,
        )
    plan = EditExecutionPlan(
        action_id=action.action_id,
        task_id=task_id,
        path=action.arguments.path,
        before_version=prepared.before_version,
        after_version=prepared.after_version,
        diff=prepared.diff,
    )
    executing_status = TaskStatusRecord(
        task_status_id=next_executing_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.EXECUTING,
        reason="用户已批准 edit_file，Runtime 开始可恢复执行",
    )
    state.record_permission_approval_executing(
        decision,
        plan,
        executing_status,
    )
    observation = resume_edit_execution(
        task_id=task_id,
        action_id=action.action_id,
        state=state,
        next_task_status_id=next_running_status_id,
    )
    return PermissionApprovalExecutionResult(
        decision=decision,
        plan=plan,
        observation=observation,
        running_status=state.task_statuses.get_current(task_id),
    )
