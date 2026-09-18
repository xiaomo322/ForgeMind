import pytest

from forgemind.runtime.permissions import (
    record_permission_rejection,
    resolve_registered_permission_decision,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
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


def make_state(
    decision_value: PermissionDecision,
) -> tuple[
    AcceptedReadFileToolAction,
    InMemoryActionRegistry,
    InMemoryPermissionDecisionRegistry,
    InMemoryObservationRegistry,
]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/private.py",
            "max_lines": 50,
            "expected_version": "sha256:v1",
        },
        reason="读取受控文件",
    )
    actions.register(action)

    requests = InMemoryPermissionRequestRegistry(actions)
    requests.register(
        PendingReadFilePermissionRequest(
            permission_request_id="permission-request-001",
            task_id="task-001",
            action_id="action-001",
            status="pending",
            action_type="tool_call",
            tool_name="read_file",
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
            task_id="task-001",
            action_id="action-001",
            decision=decision_value,
            source="user",
            raw_response="同意" if decision_value is PermissionDecision.APPROVE else "拒绝",
        )
    )
    return action, actions, decisions, InMemoryObservationRegistry(actions)


def test_approve_resumes_exact_registered_action_without_mutating_arguments() -> None:
    original, actions, decisions, observations = make_state(
        PermissionDecision.APPROVE
    )

    action, permission_check = resolve_registered_permission_decision(
        "permission-decision-001",
        actions=actions,
        decisions=decisions,
    )

    assert action is original
    assert action.arguments.max_lines == 50
    assert permission_check.action_id == "action-001"
    assert permission_check.outcome is PermissionCheckOutcome.ALLOWED
    assert permission_check.basis_ids == ("permission-decision-001",)
    with pytest.raises(KeyError):
        observations.get("action-001")


def test_reject_flows_through_denied_to_rejected_observation() -> None:
    original, actions, decisions, observations = make_state(
        PermissionDecision.REJECT
    )

    action, permission_check = resolve_registered_permission_decision(
        "permission-decision-001",
        actions=actions,
        decisions=decisions,
    )
    rejected = record_permission_rejection(
        action,
        permission_check,
        observations=observations,
    )

    assert action is original
    assert permission_check.outcome is PermissionCheckOutcome.DENIED
    assert rejected.action_id == "action-001"
    assert rejected.error.details[0].value == "permission-decision-001"
    assert observations.get("action-001") is rejected


def test_unregistered_permission_decision_cannot_resume_action() -> None:
    _, actions, decisions, _ = make_state(PermissionDecision.APPROVE)

    with pytest.raises(KeyError):
        resolve_registered_permission_decision(
            "permission-decision-999",
            actions=actions,
            decisions=decisions,
        )
