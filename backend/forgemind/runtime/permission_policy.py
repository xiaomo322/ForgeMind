"""ForgeMind V0.1 的确定性 Tool 权限策略。"""

from forgemind.schema.actions import (
    AcceptedEditFileToolAction,
    AcceptedRunCommandToolAction,
    AcceptedRunTestsToolAction,
)
from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
)


EDIT_FILE_CONFIRMATION_POLICY_ID = (
    "policy:edit_file:user-confirmation:v0.1"
)
RUN_TESTS_CONFIRMATION_POLICY_ID = "policy:run_tests:user-confirmation:v0.1"
RUN_COMMAND_CONFIRMATION_POLICY_ID = "policy:run_command:user-confirmation:v0.1"


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


def check_run_tests_permission(
    action: AcceptedRunTestsToolAction,
) -> PermissionCheckResult:
    """测试会执行项目代码，因此 V0.1 始终要求用户确认。"""

    return PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="运行测试会执行项目代码，需要用户确认",
        basis_ids=(RUN_TESTS_CONFIRMATION_POLICY_ID,),
    )


def check_run_command_permission(
    action: AcceptedRunCommandToolAction,
) -> PermissionCheckResult:
    """命令可能产生任意项目副作用，因此 V0.1 始终要求用户确认。"""

    return PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="运行命令需要用户确认",
        basis_ids=(RUN_COMMAND_CONFIRMATION_POLICY_ID,),
    )
