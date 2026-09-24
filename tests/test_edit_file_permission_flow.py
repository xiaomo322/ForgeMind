import pytest

from forgemind.runtime.permissions import (
    PermissionOutcomeNotConfirmationRequiredError,
    create_and_register_pending_edit_file_permission_request,
    record_permission_rejection,
    resolve_registered_permission_decision,
)
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.permissions import (
    PendingEditFilePermissionRequest,
    PendingReadFilePermissionRequest,
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


def make_registered_edit_action() -> tuple[
    AcceptedEditFileToolAction,
    InMemoryActionRegistry,
]:
    actions = InMemoryActionRegistry()
    action = AcceptedEditFileToolAction(
        action_id="action-edit-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "src/app.py",
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": "sha256:v1",
        },
        reason="修正折扣逻辑",
    )
    actions.register(action)
    return action, actions


def confirmation_required(action_id: str) -> PermissionCheckResult:
    return PermissionCheckResult(
        action_id=action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="修改文件需要用户确认",
        basis_ids=("permission-policy-edit-001",),
    )


def test_pending_edit_permission_keeps_complete_action_snapshot() -> None:
    action, actions = make_registered_edit_action()
    requests = InMemoryPermissionRequestRegistry(actions)

    pending = create_and_register_pending_edit_file_permission_request(
        action,
        confirmation_required(action.action_id),
        requests=requests,
        next_permission_request_id=lambda: "permission-edit-001",
    )

    assert isinstance(pending, PendingEditFilePermissionRequest)
    assert pending.arguments is action.arguments
    assert pending.arguments.old_text == "discount = 1"
    assert pending.arguments.new_text == "discount = 2"
    assert pending.arguments.expected_version == "sha256:v1"
    assert requests.get("permission-edit-001") is pending


def test_edit_permission_request_requires_confirmation_outcome() -> None:
    action, actions = make_registered_edit_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    allowed = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.ALLOWED,
        reason="错误地尝试创建询问",
        basis_ids=("permission-policy-edit-001",),
    )

    with pytest.raises(PermissionOutcomeNotConfirmationRequiredError):
        create_and_register_pending_edit_file_permission_request(
            action,
            allowed,
            requests=requests,
            next_permission_request_id=lambda: "permission-edit-001",
        )


def test_read_permission_request_cannot_snapshot_edit_action() -> None:
    action, actions = make_registered_edit_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    read_request = PendingReadFilePermissionRequest(
        permission_request_id="permission-read-001",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": action.arguments.path,
            "expected_version": action.arguments.expected_version,
        },
        reason="不能用读取授权代替修改授权",
        basis_ids=("permission-policy-read-001",),
    )

    with pytest.raises(PermissionRequestActionSnapshotMismatchError):
        requests.register(read_request)


@pytest.mark.parametrize(
    "decision_value",
    [PermissionDecision.APPROVE, PermissionDecision.REJECT],
)
def test_edit_permission_decision_resolves_exact_registered_action(
    decision_value: PermissionDecision,
) -> None:
    action, actions = make_registered_edit_action()
    requests = InMemoryPermissionRequestRegistry(actions)
    pending = create_and_register_pending_edit_file_permission_request(
        action,
        confirmation_required(action.action_id),
        requests=requests,
        next_permission_request_id=lambda: "permission-edit-001",
    )
    decisions = InMemoryPermissionDecisionRegistry(requests)
    decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="decision-edit-001",
            permission_request_id=pending.permission_request_id,
            task_id=action.task_id,
            action_id=action.action_id,
            decision=decision_value,
            source="user",
            raw_response=(
                "同意这次修改"
                if decision_value is PermissionDecision.APPROVE
                else "拒绝这次修改"
            ),
        )
    )

    resumed_action, permission_check = resolve_registered_permission_decision(
        "decision-edit-001",
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
