import pytest
from pydantic import ValidationError

from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
)


@pytest.mark.parametrize(
    "outcome",
    [
        PermissionCheckOutcome.ALLOWED,
        PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        PermissionCheckOutcome.DENIED,
    ],
)
def test_permission_check_preserves_three_distinct_outcomes(
    outcome: PermissionCheckOutcome,
) -> None:
    result = PermissionCheckResult(
        action_id="action-001",
        outcome=outcome,
        reason="根据当前权限记录得到结论",
        basis_ids=("permission-policy-001",),
    )

    assert result.outcome is outcome


def test_permission_check_rejects_observation_status_as_outcome() -> None:
    with pytest.raises(ValidationError):
        PermissionCheckResult(
            action_id="action-001",
            outcome="rejected",
            reason="错误地混用了 Observation 状态",
            basis_ids=("permission-policy-001",),
        )


def test_permission_check_requires_at_least_one_nonempty_basis_id() -> None:
    for basis_ids in ((), ("",)):
        with pytest.raises(ValidationError):
            PermissionCheckResult(
                action_id="action-001",
                outcome=PermissionCheckOutcome.ALLOWED,
                reason="缺少可追溯依据",
                basis_ids=basis_ids,
            )
