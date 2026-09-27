import pytest

from forgemind.runtime.permissions import (
    PermissionOutcomeNotConfirmationRequiredError,
    create_and_register_pending_run_command_permission_request,
    record_permission_rejection,
    resolve_registered_permission_decision,
)
from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.permissions import (
    PendingRunCommandPermissionRequest,
    PermissionCheckOutcome,
    PermissionCheckResult,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.state.permission_decision_registry import (
    InMemoryPermissionDecisionRegistry,
)
from forgemind.state.permission_request_registry import (
    InMemoryPermissionRequestRegistry,
    PermissionRequestActionSnapshotMismatchError,
)


def _registered_action() -> tuple[
    AcceptedRunCommandToolAction,
    InMemoryActionRegistry,
]:
    action = AcceptedRunCommandToolAction(
        action_id="action-command-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="run_command",
        arguments={
            "program": "python",
            "args": ("-m", "compileall", "backend"),
            "working_directory": ".",
            "timeout_seconds": 30,
        },
        reason="编译 backend 目录",
    )
    actions = InMemoryActionRegistry()
    actions.register(action)
    return action, actions


def _confirmation_required(action_id: str) -> PermissionCheckResult:
    return PermissionCheckResult(
        action_id=action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="命令会执行项目代码，需要用户确认",
        basis_ids=("permission-policy-run-command-001",),
    )


def test_pending_run_command_permission_keeps_complete_action_snapshot() -> None:
    action, actions = _registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)

    pending = create_and_register_pending_run_command_permission_request(
        action,
        _confirmation_required(action.action_id),
        requests=requests,
        next_permission_request_id=lambda: "permission-command-001",
    )

    assert isinstance(pending, PendingRunCommandPermissionRequest)
    assert pending.arguments is action.arguments
    assert pending.arguments.program == "python"
    assert pending.arguments.args == ("-m", "compileall", "backend")
    assert pending.arguments.working_directory == "."
    assert pending.arguments.timeout_seconds == 30
    assert requests.get(pending.permission_request_id) is pending


def test_run_command_permission_request_requires_confirmation_outcome() -> None:
    action, actions = _registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    allowed = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.ALLOWED,
        reason="已由策略允许",
        basis_ids=("permission-policy-run-command-001",),
    )

    with pytest.raises(PermissionOutcomeNotConfirmationRequiredError):
        create_and_register_pending_run_command_permission_request(
            action,
            allowed,
            requests=requests,
            next_permission_request_id=lambda: "permission-command-001",
        )


def test_permission_registry_rejects_changed_command_arguments() -> None:
    action, actions = _registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    changed = PendingRunCommandPermissionRequest(
        permission_request_id="permission-command-001",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type="tool_call",
        tool_name="run_command",
        arguments={
            "program": "python",
            "args": ("cleanup.py",),
            "working_directory": ".",
            "timeout_seconds": 30,
        },
        reason="参数已经被扩大",
        basis_ids=("permission-policy-run-command-001",),
    )

    with pytest.raises(PermissionRequestActionSnapshotMismatchError):
        requests.register(changed)


@pytest.mark.parametrize(
    "decision_value",
    [PermissionDecision.APPROVE, PermissionDecision.REJECT],
)
def test_run_command_user_decision_resolves_exact_registered_action(
    decision_value: PermissionDecision,
) -> None:
    action, actions = _registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    pending = create_and_register_pending_run_command_permission_request(
        action,
        _confirmation_required(action.action_id),
        requests=requests,
        next_permission_request_id=lambda: "permission-command-001",
    )
    decisions = InMemoryPermissionDecisionRegistry(requests)
    decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="decision-command-001",
            permission_request_id=pending.permission_request_id,
            task_id=action.task_id,
            action_id=action.action_id,
            decision=decision_value,
            source="user",
            raw_response=(
                "同意执行这次命令"
                if decision_value is PermissionDecision.APPROVE
                else "拒绝执行这次命令"
            ),
        )
    )

    resumed_action, permission_check = resolve_registered_permission_decision(
        "decision-command-001",
        actions=actions,
        decisions=decisions,
    )

    assert resumed_action is action
    expected_outcome = (
        PermissionCheckOutcome.ALLOWED
        if decision_value is PermissionDecision.APPROVE
        else PermissionCheckOutcome.DENIED
    )
    assert permission_check.outcome is expected_outcome

    if decision_value is PermissionDecision.REJECT:
        observations = InMemoryObservationRegistry(actions)
        rejected = record_permission_rejection(
            resumed_action,
            permission_check,
            observations=observations,
        )
        assert rejected.error.code is ObservationErrorCode.PERMISSION_DENIED
        assert observations.get(action.action_id) is rejected
