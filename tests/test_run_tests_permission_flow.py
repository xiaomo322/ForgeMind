import pytest

from forgemind.runtime.permissions import (
    PermissionOutcomeNotConfirmationRequiredError,
    create_and_register_pending_run_tests_permission_request,
    record_permission_rejection,
    resolve_registered_permission_decision,
)
from forgemind.schema.actions import AcceptedRunTestsToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.permissions import (
    PendingRunTestsPermissionRequest,
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


def make_registered_action() -> tuple[
    AcceptedRunTestsToolAction,
    InMemoryActionRegistry,
]:
    action = AcceptedRunTestsToolAction(
        action_id="action-tests-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="run_tests",
        arguments={
            "targets": ("tests/test_price.py",),
            "timeout_seconds": 30,
        },
        reason="运行价格测试",
    )
    actions = InMemoryActionRegistry()
    actions.register(action)
    return action, actions


def confirmation_required(action_id: str) -> PermissionCheckResult:
    return PermissionCheckResult(
        action_id=action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="测试会执行项目代码，需要用户确认",
        basis_ids=("permission-policy-run-tests-001",),
    )


def test_pending_run_tests_permission_keeps_complete_action_snapshot() -> None:
    action, actions = make_registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)

    pending = create_and_register_pending_run_tests_permission_request(
        action,
        confirmation_required(action.action_id),
        requests=requests,
        next_permission_request_id=lambda: "permission-tests-001",
    )

    assert isinstance(pending, PendingRunTestsPermissionRequest)
    assert pending.arguments is action.arguments
    assert pending.arguments.targets == ("tests/test_price.py",)
    assert pending.arguments.timeout_seconds == 30
    assert requests.get(pending.permission_request_id) is pending


def test_run_tests_permission_request_requires_confirmation_outcome() -> None:
    action, actions = make_registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    allowed = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.ALLOWED,
        reason="已经允许",
        basis_ids=("permission-policy-run-tests-001",),
    )

    with pytest.raises(PermissionOutcomeNotConfirmationRequiredError):
        create_and_register_pending_run_tests_permission_request(
            action,
            allowed,
            requests=requests,
            next_permission_request_id=lambda: "permission-tests-001",
        )


def test_permission_registry_rejects_widened_test_targets() -> None:
    action, actions = make_registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    widened = PendingRunTestsPermissionRequest(
        permission_request_id="permission-tests-001",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type="tool_call",
        tool_name="run_tests",
        arguments={"targets": ("tests",), "timeout_seconds": 30},
        reason="错误扩大到全部测试",
        basis_ids=("permission-policy-run-tests-001",),
    )

    with pytest.raises(PermissionRequestActionSnapshotMismatchError):
        requests.register(widened)


@pytest.mark.parametrize(
    "decision_value",
    [PermissionDecision.APPROVE, PermissionDecision.REJECT],
)
def test_run_tests_user_decision_resolves_exact_registered_action(
    decision_value: PermissionDecision,
) -> None:
    action, actions = make_registered_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    pending = create_and_register_pending_run_tests_permission_request(
        action,
        confirmation_required(action.action_id),
        requests=requests,
        next_permission_request_id=lambda: "permission-tests-001",
    )
    decisions = InMemoryPermissionDecisionRegistry(requests)
    decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="decision-tests-001",
            permission_request_id=pending.permission_request_id,
            task_id=action.task_id,
            action_id=action.action_id,
            decision=decision_value,
            source="user",
            raw_response=(
                "同意运行这组测试"
                if decision_value is PermissionDecision.APPROVE
                else "拒绝运行这组测试"
            ),
        )
    )

    resumed_action, permission_check = resolve_registered_permission_decision(
        "decision-tests-001",
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
