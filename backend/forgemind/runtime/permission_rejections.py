"""处理用户对具体 Tool 权限请求的拒绝回答。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.ids import (
    new_permission_decision_id,
    new_task_status_id,
)
from forgemind.runtime.permissions import build_permission_rejection
from forgemind.schema.observations import RejectedObservation
from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


IdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class PermissionRejectionRunningResult:
    """已经持久化的用户拒绝、终态事实和恢复状态。"""

    decision: PermissionDecisionRecord
    observation: RejectedObservation
    running_status: TaskStatusRecord


def reject_permission_request(
    *,
    task_id: str,
    permission_request_id: str,
    raw_response: str,
    state: SQLiteForgeMindState,
    next_permission_decision_id: IdFactory = new_permission_decision_id,
    next_task_status_id: IdFactory = new_task_status_id,
) -> PermissionRejectionRunningResult:
    """记录用户对一个具体权限请求的拒绝，并恢复 Agent 循环。"""

    # 第一步：读取当前任务状态和 permission_request_id 对应的权威请求，
    # 再根据请求中的 action_id 读取不可变 Action。

    # 第二步：构造 PermissionDecisionRecord。decision 固定为 REJECT，
    # source 固定为 user，raw_response 必须原样保存。

    # 第三步：构造 DENIED PermissionCheckResult。action_id 来自 Action，
    # reason 表达用户拒绝，basis_ids 只引用本次决定编号；再调用
    # build_permission_rejection() 创建尚未登记的 rejected Observation。

    # 第四步：构造 revision + 1 的 RUNNING 状态，表示 Agent 可以根据
    # 拒绝事实评估其他方案，而不是重复执行或结束任务。

    # 第五步：调用 state.record_permission_rejection_running(...) 原子
    # 写入三项事实，再返回 PermissionRejectionRunningResult。
    current_status = state.task_statuses.get_current(task_id)

    permission_request = state.permission_requests.get(
        permission_request_id
    )
    action = state.actions.get(permission_request.action_id)

    permission_decision_id = next_permission_decision_id()
    decision = PermissionDecisionRecord(
        permission_decision_id=permission_decision_id,
        permission_request_id=permission_request_id,
        task_id=task_id,
        action_id=action.action_id,
        decision=PermissionDecision.REJECT,
        source="user",
        raw_response=raw_response,
    )

    permission_check = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.DENIED,
        reason="用户已拒绝待确认权限请求",
        basis_ids=(permission_decision_id,),
    )
    observation = build_permission_rejection(
        action,
        permission_check,
    )

    running_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current_status.revision + 1,
        status=TaskStatus.RUNNING,
        reason="用户拒绝本次操作，继续评估其他方案",
    )

    state.record_permission_rejection_running(
        decision,
        observation,
        running_status,
    )

    return PermissionRejectionRunningResult(
        decision=decision,
        observation=observation,
        running_status=running_status,
    )
