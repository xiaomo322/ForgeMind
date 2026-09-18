"""Runtime 权限检查结果的处理入口。"""

from collections.abc import Callable

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
)
from forgemind.schema.permissions import (
    PendingReadFilePermissionRequest,
    PermissionCheckOutcome,
    PermissionCheckResult,
    PermissionDecision,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.state.permission_decision_registry import (
    InMemoryPermissionDecisionRegistry,
)
from forgemind.state.permission_request_registry import (
    InMemoryPermissionRequestRegistry,
)


class PermissionCheckActionMismatchError(ValueError):
    """权限检查结果引用的 Action 与当前 Action 不一致。"""


class PermissionOutcomeNotDeniedError(ValueError):
    """尝试把非 denied 权限结论记录为拒绝 Observation。"""


class PermissionOutcomeNotConfirmationRequiredError(ValueError):
    """尝试把非 confirmation_required 结论创建为待确认请求。"""


PermissionRequestIdFactory = Callable[[], str]


def create_and_register_pending_read_file_permission_request(
    action: AcceptedReadFileToolAction,
    permission_check: PermissionCheckResult,
    *,
    requests: InMemoryPermissionRequestRegistry,
    next_permission_request_id: PermissionRequestIdFactory,
) -> PendingReadFilePermissionRequest:
    """把需要确认的权限结论转换为已登记的用户询问。"""

    if permission_check.action_id != action.action_id:
        raise PermissionCheckActionMismatchError(
            "权限检查结果与当前 Action 的 action_id 不一致"
        )

    # allowed 应继续检查/执行，denied 应形成拒绝 Observation；只有
    # confirmation_required 能进入等待用户的分支。
    if (
        permission_check.outcome
        is not PermissionCheckOutcome.CONFIRMATION_REQUIRED
    ):
        raise PermissionOutcomeNotConfirmationRequiredError(
            "只有 confirmation_required 能创建待确认权限请求"
        )

    pending = PendingReadFilePermissionRequest(
        permission_request_id=next_permission_request_id(),
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments,
        reason=permission_check.reason,
        basis_ids=permission_check.basis_ids,
    )

    # 先登记再返回，确保展示给用户的询问已经成为 State 中可追溯的
    # 权威记录。登记失败时不能进入 WAITING_USER 或展示临时请求。
    requests.register(pending)
    return pending


def resolve_registered_permission_decision(
    permission_decision_id: str,
    *,
    actions: InMemoryActionRegistry,
    decisions: InMemoryPermissionDecisionRegistry,
) -> tuple[AcceptedReadFileToolAction, PermissionCheckResult]:
    """取回权威 Action，并把已登记用户决定转换为权限结论。"""

    # 只按编号读取已经登记的权威记录。调用方不能把一条尚未写入
    # State 的临时“同意”或“拒绝”直接送入执行链路。
    decision = decisions.get(permission_decision_id)

    # 后续流程必须继续使用 State 中原来登记的不可变 Action。只返回
    # action_id 会让调用方有机会传入同编号、但参数已扩大的伪造副本。
    action = actions.get(decision.action_id)

    if decision.decision is PermissionDecision.APPROVE:
        outcome = PermissionCheckOutcome.ALLOWED
        reason = "用户已批准待确认权限请求"
    else:
        outcome = PermissionCheckOutcome.DENIED
        reason = "用户已拒绝待确认权限请求"

    # 用户决定只恢复权限分支。allowed 后仍需继续执行版本、安全和
    # 环境检查；这里不调用 Tool，也不生成成功 Observation。
    permission_check = PermissionCheckResult(
        action_id=action.action_id,
        outcome=outcome,
        reason=reason,
        basis_ids=(decision.permission_decision_id,),
    )
    return action, permission_check


def record_permission_rejection(
    action: AcceptedReadFileToolAction,
    permission_check: PermissionCheckResult,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """创建并记录 Runtime 在执行工具前产生的权限拒绝事实。

    Agent 只能提出行动，真正的权限检查发生在 Runtime，因此 Runtime
    才能生成这条 Observation。它沿用已接受 Action 的 ``action_id``，
    让 Agent 能明确知道究竟是哪一次行动被拒绝。
    """
    # 权限结论必须精确属于当前 Action。只检查“都是读取文件”仍可能
    # 把另一文件或另一次请求的拒绝决定错误地应用到这里。
    if permission_check.action_id != action.action_id:
        raise PermissionCheckActionMismatchError(
            "权限检查结果与当前 Action 的 action_id 不一致"
        )

    # confirmation_required 表示仍需询问用户，allowed 表示可以继续；
    # 二者都不能伪装成已经发生的权限拒绝事实。
    if permission_check.outcome is not PermissionCheckOutcome.DENIED:
        raise PermissionOutcomeNotDeniedError(
            "只有 denied 权限结论可以转换为 RejectedObservation"
        )

    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message=permission_check.reason,
            details=tuple(
                ObservationErrorDetail(
                    key="permission_basis_id",
                    value=basis_id,
                )
                for basis_id in permission_check.basis_ids
            ),
        ),
    )

    # 必须先写入 State 再返回。若记录失败，就不能让 Agent 误以为
    # 这条拒绝已经成为可在下一轮依赖的历史事实。
    observations.record(rejected)
    return rejected
