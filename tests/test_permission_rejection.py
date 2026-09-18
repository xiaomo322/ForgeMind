import pytest

from forgemind.runtime.permissions import (
    PermissionCheckActionMismatchError,
    PermissionOutcomeNotDeniedError,
    record_permission_rejection,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def test_runtime_records_permission_rejection_for_registered_action() -> None:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction.model_validate(
        {
            "action_id": "action-001",
            "task_id": "task-001",
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/private.py"},
            "reason": "读取受控文件",
        }
    )
    actions.register(action)
    observations = InMemoryObservationRegistry(actions)
    permission_check = PermissionCheckResult(
        action_id="action-001",
        outcome=PermissionCheckOutcome.DENIED,
        reason="用户未授权读取 src/private.py",
        basis_ids=("permission-decision-001",),
    )

    rejected = record_permission_rejection(
        action,
        permission_check,
        observations=observations,
    )

    assert rejected.action_id == "action-001"
    assert rejected.status == "rejected"
    assert rejected.error.code is ObservationErrorCode.PERMISSION_DENIED
    assert rejected.error.message == permission_check.reason
    assert rejected.error.details[0].value == "permission-decision-001"
    assert actions.get("action-001") is action
    assert observations.get("action-001") is rejected


def test_runtime_rejects_permission_check_for_another_action() -> None:
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
    observations = InMemoryObservationRegistry(actions)
    permission_check = PermissionCheckResult(
        action_id="action-999",
        outcome=PermissionCheckOutcome.DENIED,
        reason="另一行动的拒绝结果",
        basis_ids=("permission-decision-999",),
    )

    with pytest.raises(PermissionCheckActionMismatchError):
        record_permission_rejection(
            action,
            permission_check,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get("action-001")


@pytest.mark.parametrize(
    "outcome",
    [
        PermissionCheckOutcome.ALLOWED,
        PermissionCheckOutcome.CONFIRMATION_REQUIRED,
    ],
)
def test_runtime_does_not_turn_non_denied_check_into_rejection(
    outcome: PermissionCheckOutcome,
) -> None:
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
    observations = InMemoryObservationRegistry(actions)
    permission_check = PermissionCheckResult(
        action_id="action-001",
        outcome=outcome,
        reason="当前权限结论不是明确拒绝",
        basis_ids=("permission-policy-001",),
    )

    with pytest.raises(PermissionOutcomeNotDeniedError):
        record_permission_rejection(
            action,
            permission_check,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get("action-001")
