from pathlib import Path
import sys

import pytest

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
from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_sqlite_state_survives_wait_approve_execute_restarts(
    tmp_path: Path,
) -> None:
    """等待用户、批准和执行跨多次重启仍保持同一条证据链。"""

    # 第一步：确定 state.db 路径，并模拟第一次启动创建四个 Registry。
    database_path = tmp_path / "state.db"
    state_1 = SQLiteForgeMindState.open(database_path)
    # 第二步：创建 run_command Decision，执行当前 Python 输出固定标记。
    decision = RunCommandToolCallDecision(
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-c", "print('forgemind-persistent-state-ok')"),
            working_directory=".",
            timeout_seconds=30,
        ),
        reason="验证 SQLite State 跨重启恢复",
    )
    # 第三步：Runtime 接受并持久化 Action，使用固定 action_id。
    action = accept_and_register_run_command_decision(
        decision,
        task_id="task-persistent-001",
        registry=state_1.actions,
        next_action_id=lambda: "action-persistent-001",
    )
    # 第四步：创建 confirmation_required 结果和 pending 权限请求；
    # 此时不要保存用户决定，也不要执行命令，并用 pytest.raises(KeyError)
    # 证明 Observation Registry 中还没有这个 action_id。
    confirmation_required = PermissionCheckResult(
        action_id=action.action_id,
        outcome=PermissionCheckOutcome.CONFIRMATION_REQUIRED,
        reason="真实命令需要用户确认",
        basis_ids=("policy-persistent-command-001",),
    )

    pending = create_and_register_pending_run_command_permission_request(
        action,
        confirmation_required,
        requests=state_1.permission_requests,
        next_permission_request_id=lambda: "permission-persistent-001",
    )

    with pytest.raises(KeyError):
        state_1.observations.get(action.action_id)
    # 第五步：重新打开统一 State 模拟程序重启。分别恢复 Action 和 pending，
    # 断言它们与原记录值相等，但不是原来的 Python 对象。
    state_2 = SQLiteForgeMindState.open(database_path)

    restored_action = state_2.actions.get(action.action_id)
    restored_pending = state_2.permission_requests.get(
        pending.permission_request_id
    )

    assert restored_action == action
    assert restored_action is not action
    assert restored_pending == pending
    assert restored_pending is not pending

    # 第六步：使用恢复后的 pending 记录用户 approve 决定。
    user_decision = PermissionDecisionRecord(
        permission_decision_id="decision-persistent-001",
        permission_request_id=restored_pending.permission_request_id,
        task_id=restored_pending.task_id,
        action_id=restored_pending.action_id,
        decision=PermissionDecision.APPROVE,
        source="user",
        raw_response="同意执行这次命令",
    )

    state_2.permission_decisions.record(user_decision)
    # 第七步：再次打开统一 State 模拟第二次重启，只按决定 ID 恢复
    # 权威 Action 和 allowed 权限结论。
    state_3 = SQLiteForgeMindState.open(database_path)

    resumed_action, allowed = resolve_registered_permission_decision(
        user_decision.permission_decision_id,
        actions=state_3.actions,
        decisions=state_3.permission_decisions,
    )

    assert resumed_action == action
    assert resumed_action is not action
    assert allowed.outcome is PermissionCheckOutcome.ALLOWED

    # 第八步：使用恢复后的 Action 执行真实命令；allowed_programs 中
    # python 映射到 Path(sys.executable).resolve()，Observation 写入 SQLite。
    observation = execute_run_command_action(
        resumed_action,
        project_root=tmp_path,
        allowed_programs={
            "python": Path(sys.executable).resolve(),
        },
        observations=state_3.observations,
    )
    # 第九步：第三次打开统一 State，再按 action_id 恢复最终 Observation。
    state_4 = SQLiteForgeMindState.open(database_path)

    restored_observation = state_4.observations.get(action.action_id)

    # 第十步：断言 status=success、exit_code=0、stdout 含
    # "forgemind-persistent-state-ok"，并确认四类记录都仍可读取。
    assert restored_observation == observation
    assert restored_observation is not observation
    assert restored_observation.status == "success"
    assert restored_observation.result.exit_code == 0
    assert (
        "forgemind-persistent-state-ok"
        in restored_observation.result.stdout
    )

    assert state_4.actions.get(action.action_id) == action
    assert (
        state_4.permission_requests.get(pending.permission_request_id)
        == pending
    )
    assert (
        state_4.permission_decisions.get(
            user_decision.permission_decision_id
        )
            == user_decision
    )
