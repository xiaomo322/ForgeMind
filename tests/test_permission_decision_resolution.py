import pytest

from forgemind.runtime.permissions import (
    record_permission_rejection,
    resolve_registered_permission_decision,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.permissions import (
    PendingReadFilePermissionRequest,
    PermissionCheckOutcome,
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
)


def make_registered_decision(
    decision: PermissionDecision,
) -> tuple[
    AcceptedReadFileToolAction,
    InMemoryActionRegistry,
    InMemoryPermissionDecisionRegistry,
]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/private.py"},
        reason="读取受控文件",
    )
    actions.register(action)

    requests = InMemoryPermissionRequestRegistry(actions)
    requests.register(
        PendingReadFilePermissionRequest(
            permission_request_id="permission-request-001",
            task_id=action.task_id,
            action_id=action.action_id,
            status="pending",
            action_type=action.action_type,
            tool_name=action.tool_name,
            arguments=action.arguments,
            reason="该路径需要用户确认",
            basis_ids=("permission-policy-001",),
        )
    )

    decisions = InMemoryPermissionDecisionRegistry(requests)
    decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="permission-decision-001",
            permission_request_id="permission-request-001",
            task_id=action.task_id,
            action_id=action.action_id,
            decision=decision,
            source="user",
            raw_response="这是用户的明确决定",
        )
    )
    return action, actions, decisions


@pytest.mark.parametrize(
    ("decision", "expected_outcome"),
    [
        (PermissionDecision.APPROVE, PermissionCheckOutcome.ALLOWED),
        (PermissionDecision.REJECT, PermissionCheckOutcome.DENIED),
    ],
)
def test_runtime_resolves_registered_user_decision_to_permission_outcome(
    decision: PermissionDecision,
    expected_outcome: PermissionCheckOutcome,
) -> None:
    action, _, decisions = make_registered_decision(decision)

    result = resolve_registered_permission_decision(
        "permission-decision-001",
        decisions=decisions,
    )

    assert result.action_id == action.action_id
    assert result.outcome is expected_outcome
    assert result.basis_ids == ("permission-decision-001",)


def test_rejected_user_decision_reaches_rejected_observation() -> None:
    action, actions, decisions = make_registered_decision(
        PermissionDecision.REJECT
    )
    observations = InMemoryObservationRegistry(actions)

    permission_check = resolve_registered_permission_decision(
        "permission-decision-001",
        decisions=decisions,
    )
    rejected = record_permission_rejection(
        action,
        permission_check,
        observations=observations,
    )

    assert rejected.status == "rejected"
    assert rejected.error.code is ObservationErrorCode.PERMISSION_DENIED
    assert rejected.error.details[0].value == "permission-decision-001"
    assert observations.get(action.action_id) is rejected


def test_runtime_rejects_unknown_permission_decision_id() -> None:
    _, _, decisions = make_registered_decision(PermissionDecision.APPROVE)

    with pytest.raises(KeyError):
        resolve_registered_permission_decision(
            "permission-decision-999",
            decisions=decisions,
        )
