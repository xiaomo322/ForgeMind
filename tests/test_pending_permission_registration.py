import pytest

from forgemind.runtime.permissions import (
    PermissionCheckActionMismatchError,
    PermissionOutcomeNotConfirmationRequiredError,
    create_and_register_pending_read_file_permission_request,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.permissions import (
    PendingReadFilePermissionRequest,
    PermissionCheckOutcome,
    PermissionCheckResult,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.permission_request_registry import (
    DuplicatePermissionRequestIdError,
    InMemoryPermissionRequestRegistry,
    PermissionRequestActionSnapshotMismatchError,
    UnknownPermissionRequestActionError,
)


def make_action(action_id: str = "action-001") -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/private.py",
            "start_line": 10,
            "max_lines": 50,
            "expected_version": "sha256:abc",
        },
        reason="读取受控文件",
    )


def make_check(
    outcome: PermissionCheckOutcome = PermissionCheckOutcome.CONFIRMATION_REQUIRED,
    action_id: str = "action-001",
) -> PermissionCheckResult:
    return PermissionCheckResult(
        action_id=action_id,
        outcome=outcome,
        reason="该路径需要用户确认",
        basis_ids=("permission-policy-001",),
    )


def test_runtime_creates_and_registers_pending_permission_request() -> None:
    actions = InMemoryActionRegistry()
    action = make_action()
    actions.register(action)
    requests = InMemoryPermissionRequestRegistry(actions)

    pending = create_and_register_pending_read_file_permission_request(
        action,
        make_check(),
        requests=requests,
        next_permission_request_id=lambda: "permission-request-001",
    )

    assert pending.permission_request_id == "permission-request-001"
    assert pending.action_id == action.action_id
    assert pending.arguments is action.arguments
    assert pending.status == "pending"
    assert requests.get("permission-request-001") is pending


def test_runtime_rejects_check_for_another_action_before_registration() -> None:
    actions = InMemoryActionRegistry()
    action = make_action()
    actions.register(action)
    requests = InMemoryPermissionRequestRegistry(actions)

    with pytest.raises(PermissionCheckActionMismatchError):
        create_and_register_pending_read_file_permission_request(
            action,
            make_check(action_id="action-999"),
            requests=requests,
            next_permission_request_id=lambda: "permission-request-001",
        )

    with pytest.raises(KeyError):
        requests.get("permission-request-001")


@pytest.mark.parametrize(
    "outcome",
    [PermissionCheckOutcome.ALLOWED, PermissionCheckOutcome.DENIED],
)
def test_runtime_only_creates_pending_request_for_confirmation_required(
    outcome: PermissionCheckOutcome,
) -> None:
    actions = InMemoryActionRegistry()
    action = make_action()
    actions.register(action)
    requests = InMemoryPermissionRequestRegistry(actions)

    with pytest.raises(PermissionOutcomeNotConfirmationRequiredError):
        create_and_register_pending_read_file_permission_request(
            action,
            make_check(outcome=outcome),
            requests=requests,
            next_permission_request_id=lambda: "permission-request-001",
        )


def test_permission_request_registry_rejects_duplicate_id_without_overwrite() -> None:
    actions = InMemoryActionRegistry()
    action = make_action()
    actions.register(action)
    requests = InMemoryPermissionRequestRegistry(actions)
    original = PendingReadFilePermissionRequest(
        permission_request_id="permission-request-001",
        task_id="task-001",
        action_id="action-001",
        status="pending",
        action_type="tool_call",
        tool_name="read_file",
        arguments=action.arguments,
        reason="原始询问",
        basis_ids=("permission-policy-001",),
    )
    duplicate = original.model_copy(update={"reason": "不得覆盖原始询问"})

    requests.register(original)
    with pytest.raises(DuplicatePermissionRequestIdError):
        requests.register(duplicate)

    assert requests.get("permission-request-001") is original


def test_permission_request_registry_rejects_unknown_action() -> None:
    actions = InMemoryActionRegistry()
    requests = InMemoryPermissionRequestRegistry(actions)
    action = make_action()
    pending = PendingReadFilePermissionRequest(
        permission_request_id="permission-request-001",
        task_id="task-001",
        action_id=action.action_id,
        status="pending",
        action_type="tool_call",
        tool_name="read_file",
        arguments=action.arguments,
        reason="该路径需要用户确认",
        basis_ids=("permission-policy-001",),
    )

    with pytest.raises(UnknownPermissionRequestActionError):
        requests.register(pending)


def test_permission_request_registry_rejects_changed_action_snapshot() -> None:
    actions = InMemoryActionRegistry()
    action = make_action()
    actions.register(action)
    requests = InMemoryPermissionRequestRegistry(actions)
    pending = PendingReadFilePermissionRequest(
        permission_request_id="permission-request-001",
        task_id="task-001",
        action_id="action-001",
        status="pending",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/another.py"},
        reason="不得把询问范围换成另一个文件",
        basis_ids=("permission-policy-001",),
    )

    with pytest.raises(PermissionRequestActionSnapshotMismatchError):
        requests.register(pending)
