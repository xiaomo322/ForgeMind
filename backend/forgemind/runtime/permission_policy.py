"""ForgeMind V0.1 的确定性 Tool 权限策略。"""

from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
)


EDIT_FILE_CONFIRMATION_POLICY_ID = (
    "policy:edit_file:user-confirmation:v0.1"
)


def check_edit_file_permission(
    action: AcceptedEditFileToolAction,
) -> PermissionCheckResult:
    """V0.1 中每个具体 edit_file Action 都必须由用户确认。"""

    # 第一步：构造并返回 PermissionCheckResult。
    # action_id 必须来自当前 AcceptedAction。
    # outcome 固定为 PermissionCheckOutcome.CONFIRMATION_REQUIRED。
    # reason 使用“修改文件需要用户确认”。
    # basis_ids 是只包含 EDIT_FILE_CONFIRMATION_POLICY_ID 的一元素元组。
    return PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="修改文件需要用户确认",
        basis_ids=(EDIT_FILE_CONFIRMATION_POLICY_ID,),
    )
