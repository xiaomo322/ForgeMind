import pytest

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.permissions import (
    PendingReadFilePermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.permission_decision_registry import (
    DuplicatePermissionDecisionIdError,
    DuplicatePermissionRequestDecisionError,
    InMemoryPermissionDecisionRegistry,
    PermissionDecisionRequestMismatchError,
    UnknownPermissionRequestIdError,
)
from forgemind.state.permission_request_registry import (
    InMemoryPermissionRequestRegistry,
)


def make_registries() -> tuple[
    InMemoryPermissionRequestRegistry,
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
    return requests, InMemoryPermissionDecisionRegistry(requests)


def make_decision(
    *,
    permission_decision_id: str = "permission-decision-001",
    permission_request_id: str = "permission-request-001",
    task_id: str = "task-001",
    action_id: str = "action-001",
    decision: PermissionDecision = PermissionDecision.APPROVE,
) -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        permission_decision_id=permission_decision_id,
        permission_request_id=permission_request_id,
        task_id=task_id,
        action_id=action_id,
        decision=decision,
        source="user",
        raw_response="同意",
    )


def test_permission_decision_registry_records_decision_for_pending_request() -> None:
    _, decisions = make_registries()
    decision = make_decision()

    decisions.record(decision)

    assert decisions.get("permission-decision-001") is decision
    assert decisions.get_for_request("permission-request-001") is decision


def test_permission_decision_registry_rejects_unknown_request() -> None:
    requests, decisions = make_registries()
    decision = make_decision(permission_request_id="permission-request-999")

    with pytest.raises(UnknownPermissionRequestIdError):
        decisions.record(decision)

    with pytest.raises(KeyError):
        decisions.get(decision.permission_decision_id)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("task_id", "task-999"), ("action_id", "action-999")],
)
def test_permission_decision_registry_rejects_request_link_mismatch(
    field: str,
    invalid_value: str,
) -> None:
    _, decisions = make_registries()
    values = {field: invalid_value}
    decision = make_decision(**values)

    with pytest.raises(PermissionDecisionRequestMismatchError):
        decisions.record(decision)


def test_permission_decision_registry_rejects_duplicate_decision_id() -> None:
    _, decisions = make_registries()
    original = make_decision()
    duplicate = make_decision(decision=PermissionDecision.REJECT)

    decisions.record(original)
    with pytest.raises(DuplicatePermissionDecisionIdError):
        decisions.record(duplicate)

    assert decisions.get("permission-decision-001") is original


def test_permission_decision_registry_rejects_second_decision_for_same_request() -> None:
    _, decisions = make_registries()
    original = make_decision()
    second = make_decision(
        permission_decision_id="permission-decision-002",
        decision=PermissionDecision.REJECT,
    )

    decisions.record(original)
    with pytest.raises(DuplicatePermissionRequestDecisionError):
        decisions.record(second)

    assert decisions.get_for_request("permission-request-001") is original
