from pathlib import Path

from forgemind.runtime.acceptance import (
    accept_and_register_run_tests_decision,
)
from forgemind.runtime.permissions import (
    create_and_register_pending_run_tests_permission_request,
    resolve_registered_permission_decision,
)
from forgemind.runtime.run_tests_execution import execute_run_tests_action
from forgemind.schema.decisions import RunTestsToolCallDecision
from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.run_tests import TestOutcome as Outcome
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.state.permission_decision_registry import (
    InMemoryPermissionDecisionRegistry,
)
from forgemind.state.permission_request_registry import (
    InMemoryPermissionRequestRegistry,
)


def test_run_tests_real_module_flow_records_authoritative_result(
    tmp_path: Path,
) -> None:
    # 第一步：在 tmp_path/project/tests 下创建真实 test_pricing.py。
    # 文件中写两个测试：一个 assert True，一个 assert False。
    project_root = tmp_path / "project"
    test_file = project_root / "tests" / "test_pricing.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_passes():\n"
        "    assert True\n"
        "\n"
        "def test_fails():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    # 第二步：创建 InMemoryActionRegistry，并基于它创建
    # 权限请求、权限决定和 Observation 注册表。
    actions = InMemoryActionRegistry()
    permission_requests = InMemoryPermissionRequestRegistry(actions)
    permission_decisions = InMemoryPermissionDecisionRegistry(
        permission_requests
    )
    observations = InMemoryObservationRegistry(actions)

    # 第三步：构造 RunTestsToolCallDecision。目标必须使用项目相对路径
    # tests/test_pricing.py，超时设为 30 秒，Decision 不提供 action_id。
    decision = RunTestsToolCallDecision(
        action_type="tool_call",
        tool_name="run_tests",
        arguments={
            "targets": ("tests/test_pricing.py",),
            "timeout_seconds": 30,
        },
        reason="验证价格模块",
    )

    # 第四步：调用 accept_and_register_run_tests_decision，让 Runtime
    # 分配固定编号 action-run-tests-module-001 并登记 AcceptedAction。
    action = accept_and_register_run_tests_decision(
        decision,
        task_id="task-run-tests-module-001",
        registry=actions,
        next_action_id=lambda: "action-run-tests-module-001",
    )

    # 第五步：保存针对这一个 Action 的完整待确认权限请求快照。
    permission_check = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="测试会执行项目代码，需要用户确认",
        basis_ids=("permission-policy-run-tests-module-001",),
    )
    pending = create_and_register_pending_run_tests_permission_request(
        action,
        permission_check,
        requests=permission_requests,
        next_permission_request_id=(
            lambda: "permission-run-tests-module-001"
        ),
    )

    # 第六步：记录用户对该询问的批准，再只按决定编号恢复权威 Action。
    permission_decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="decision-run-tests-module-001",
            permission_request_id=pending.permission_request_id,
            task_id=action.task_id,
            action_id=action.action_id,
            decision=PermissionDecision.APPROVE,
            source="user",
            raw_response="同意运行这组测试",
        )
    )
    resumed_action, approved_check = resolve_registered_permission_decision(
        "decision-run-tests-module-001",
        actions=actions,
        decisions=permission_decisions,
    )
    assert pending.arguments is action.arguments
    assert resumed_action is action
    assert approved_check.outcome is PermissionCheckOutcome.ALLOWED

    # 第七步：批准后才调用 execute_run_tests_action，让完整流程运行 pytest。
    observation = execute_run_tests_action(
        resumed_action,
        project_root=project_root,
        observations=observations,
    )

    # 第八步：确认 Action Registry 返回的对象就是 action；Observation
    # 顶层 status 为 success，因为 Tool 成功取得了完整测试报告。
    assert actions.get(action.action_id) is action
    assert observation.status == "success"

    # 第九步：确认 result.test_outcome 是 Outcome.FAILED，并检查真实统计：
    # collected=2、passed=1、failed=1、errors=0、skipped=0、exit_code=1。
    assert observation.result.test_outcome is Outcome.FAILED
    assert observation.result.collected == 2
    assert observation.result.passed == 1
    assert observation.result.failed == 1
    assert observation.result.errors == 0
    assert observation.result.skipped == 0
    assert observation.result.exit_code == 1

    # 第十步：确认 result.targets 与 Decision 的 targets 相同，stdout
    # 包含 "1 failed"，且 Observation Registry 返回同一个 observation。
    assert observation.result.targets == decision.arguments.targets
    assert "1 failed" in observation.result.stdout
    assert observations.get(action.action_id) is observation
