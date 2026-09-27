from pathlib import Path
import sys

from forgemind.runtime.acceptance import (
    accept_and_register_run_command_decision,
)
from forgemind.runtime.permissions import (
    create_and_register_pending_run_command_permission_request,
    resolve_registered_permission_decision,
)
from forgemind.runtime.run_command_execution import execute_run_command_action
from forgemind.schema.decisions import RunCommandToolCallDecision
from forgemind.schema.permissions import (
    PermissionCheckOutcome,
    PermissionCheckResult,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.run_command import RunCommandArguments
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.state.permission_decision_registry import (
    InMemoryPermissionDecisionRegistry,
)
from forgemind.state.permission_request_registry import (
    InMemoryPermissionRequestRegistry,
)


def test_run_command_real_approved_flow_records_authoritative_result(
    tmp_path: Path,
) -> None:
    """真实命令只在用户批准后执行，并把权威结果写入 State。"""

    # 第一步：创建 Action、权限请求、权限决定和 Observation 四个注册表。
    actions = InMemoryActionRegistry()
    permission_requests = InMemoryPermissionRequestRegistry(actions)
    permission_decisions = InMemoryPermissionDecisionRegistry(
        permission_requests
    )
    observations = InMemoryObservationRegistry(actions)
    # 第二步：创建 Agent Decision。命令使用当前 Python 输出固定文字，
    # working_directory 指向项目根目录，不能让 Agent 提供 action_id。
    decision = RunCommandToolCallDecision(
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-c", "print('forgemind-command-ok')"),
            working_directory=".",
            timeout_seconds=30,
        ),
        reason="验证 run_command 真实完整流程",
    )
    # 第三步：Runtime 接受并注册 Decision；测试注入确定的 action_id。
    action = accept_and_register_run_command_decision(
        decision,
        task_id="task-command-module-001",
        registry=actions,
        next_action_id=lambda: "action-command-module-001",
    )
    # 第四步：构造 confirmation_required 权限结论，绑定同一 action_id。
    confirmation_required = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="命令会启动真实进程，需要用户确认",
        basis_ids=("permission-policy-command-module-001",),
    )
    # 第五步：创建并登记 pending 权限请求，保存完整命令参数快照。
    pending = create_and_register_pending_run_command_permission_request(
        action,
        confirmation_required,
        requests=permission_requests,
        next_permission_request_id=lambda: "permission-command-module-001",
    )
    # 第六步：登记用户 approve 决定，必须引用 pending 和同一 Action。
    permission_decisions.record(
        PermissionDecisionRecord(
            permission_decision_id="decision-command-module-001",
            permission_request_id=pending.permission_request_id,
            task_id=action.task_id,
            action_id=action.action_id,
            decision=PermissionDecision.APPROVE,
            source="user",
            raw_response="同意执行这次命令",
        )
    )
    # 第七步：按 permission_decision_id 恢复原 Action 和 allowed 结论；
    # 断言恢复对象就是第三步登记的同一个 action。
    resumed_action, allowed = resolve_registered_permission_decision(
        "decision-command-module-001",
        actions=actions,
        decisions=permission_decisions,
    )

    assert resumed_action is action
    assert allowed.outcome is PermissionCheckOutcome.ALLOWED
    # 第八步：调用 execute_run_command_action。允许列表把 python 别名
    # 映射到 Path(sys.executable).resolve()，这一步会启动真实子进程。
    observation = execute_run_command_action(
        resumed_action,
        project_root=tmp_path,
        allowed_programs={
            "python": Path(sys.executable).resolve(),
        },
        observations=observations,
    )
    print("\n--- run_command 真实结果 ---")
    print("status:", observation.status)
    print("exit_code:", observation.result.exit_code)
    print("stdout:", repr(observation.result.stdout))
    print("stderr:", repr(observation.result.stderr))
    print("duration_ms:", observation.result.duration_ms)
    print("working_directory:", observation.result.working_directory)
    print("args:", observation.result.args)
    # 第九步：断言 Observation 顶层 status 是 success、退出码为 0、
    # stdout 包含 "forgemind-command-ok"，且参数与 Decision 一致。
    assert observation.status == "success"
    assert observation.result.exit_code == 0
    assert "forgemind-command-ok" in observation.result.stdout
    assert observation.result.args == decision.arguments.args

    # 第十步：断言 Observation 注册表按 action_id 取得同一个对象。
    assert observations.get(action.action_id) is observation
