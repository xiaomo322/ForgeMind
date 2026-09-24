from pathlib import Path

from forgemind.runtime.acceptance import (
    accept_and_register_edit_file_decision,
)
from forgemind.runtime.edit_file_execution import execute_edit_file_action
from forgemind.runtime.permissions import (
    create_and_register_pending_edit_file_permission_request,
    resolve_registered_permission_decision,
)
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.decisions import EditFileToolCallDecision
from forgemind.schema.permissions import (
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
)


def test_edit_file_approved_action_completes_real_module_flow(
    tmp_path: Path,
) -> None:
    # 第一步：创建真实项目文件，并保存用户将要批准的初始版本。
    project_root = tmp_path / "project"
    target = project_root / "src" / "pricing.py"
    target.parent.mkdir(parents=True)
    initial_content = b"price = 100\ndiscount = 1\n"
    target.write_bytes(initial_content)
    initial_version = calculate_content_version(initial_content)

    # 第二步：建立本次流程共用的 Action、权限和 Observation State。
    actions = InMemoryActionRegistry()
    permission_requests = InMemoryPermissionRequestRegistry(actions)
    permission_decisions = InMemoryPermissionDecisionRegistry(
        permission_requests
    )
    observations = InMemoryObservationRegistry(actions)

    # 第三步：模拟 Agent 产生不带 action_id 的 edit_file Decision。
    decision = EditFileToolCallDecision(
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "src/pricing.py",
            "old_text": "discount = 1",
            "new_text": "discount = 2",
            "expected_version": initial_version,
        },
        reason="修正折扣值",
    )

    # 第四步：Runtime 分配 action_id，并登记不可变 AcceptedAction。
    action = accept_and_register_edit_file_decision(
        decision,
        task_id="task-module-001",
        registry=actions,
        next_action_id=lambda: "action-edit-module-001",
    )

    # 第五步：Runtime 创建保存完整 Action 参数快照的待确认请求。
    permission_check = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="修改文件需要用户确认",
        basis_ids=("permission-policy-edit-001",),
    )
    pending = create_and_register_pending_edit_file_permission_request(
        action,
        permission_check,
        requests=permission_requests,
        next_permission_request_id=lambda: "permission-edit-module-001",
    )

    # 第六步：记录用户对这一个 permission_request 的明确批准。
    permission_decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="decision-edit-module-001",
            permission_request_id=pending.permission_request_id,
            task_id=action.task_id,
            action_id=action.action_id,
            decision=PermissionDecision.APPROVE,
            source="user",
            raw_response="同意这次修改",
        )
    )
    # 第七步：只按 permission_decision_id 从 State 恢复原 Action 和结论。
    resumed_action, approved_check = resolve_registered_permission_decision(
        "decision-edit-module-001",
        actions=actions,
        decisions=permission_decisions,
    )
    # 第八步：确认恢复的是同一 Action 且结果为 allowed，然后执行修改。
    assert pending.arguments is action.arguments
    assert resumed_action is action
    assert approved_check.outcome is PermissionCheckOutcome.ALLOWED

    observation = execute_edit_file_action(
        resumed_action,
        project_root=project_root,
        observations=observations,
    )

    # 第九步：验证真实文件、版本、diff 与 Observation Registry 证据。
    expected_content = b"price = 100\ndiscount = 2\n"

    assert observation.status == "success"
    assert target.read_bytes() == expected_content
    assert observation.result.before_version == initial_version
    assert observation.result.after_version == calculate_content_version(
        expected_content
    )
    assert "-discount = 1" in observation.result.diff
    assert "+discount = 2" in observation.result.diff
    assert observations.get(action.action_id) is observation
