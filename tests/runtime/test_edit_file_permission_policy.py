"""验证 V0.1 edit_file 默认要求逐 Action 用户确认。"""

from forgemind.runtime.permission_policy import (
    EDIT_FILE_CONFIRMATION_POLICY_ID,
    check_edit_file_permission,
)
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.permissions import PermissionCheckOutcome


def test_edit_file_requires_confirmation_for_exact_action() -> None:
    action = AcceptedEditFileToolAction(
        action_id="action-edit-policy-1",
        task_id="task-edit-policy",
        action_type="tool_call",
        tool_name="edit_file",
        arguments=EditFileArguments(
            path="app.py",
            old_text="discount = 1",
            new_text="discount = 0.8",
            expected_version="sha256:approved-version",
        ),
        reason="修正折扣值",
    )

    result = check_edit_file_permission(action)

    assert result.action_id == action.action_id
    assert result.outcome is PermissionCheckOutcome.CONFIRMATION_REQUIRED
    assert result.basis_ids == (EDIT_FILE_CONFIRMATION_POLICY_ID,)
    assert "修改文件" in result.reason
