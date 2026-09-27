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
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_observation_registry import (
    SQLiteObservationRegistry,
)
from forgemind.state.sqlite_permission_decision_registry import (
    SQLitePermissionDecisionRegistry,
)
from forgemind.state.sqlite_permission_request_registry import (
    SQLitePermissionRequestRegistry,
)


def _open_state(database_path: Path):
    """模拟一次进程启动时，从同一数据库建立四个 Registry。"""

    actions = SQLiteActionRegistry(database_path)
    requests = SQLitePermissionRequestRegistry(database_path, actions)
    decisions = SQLitePermissionDecisionRegistry(database_path, requests)
    observations = SQLiteObservationRegistry(database_path, actions)
    return actions, requests, decisions, observations


def test_sqlite_state_survives_wait_approve_execute_restarts(
    tmp_path: Path,
) -> None:
    """等待用户、批准和执行跨多次重启仍保持同一条证据链。"""

    # 第一步：确定 state.db 路径，并模拟第一次启动创建四个 Registry。
    database_path = tmp_path / "state.db"
    actions_1, requests_1, decisions_1, observations_1 = _open_state(
        database_path
    )
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
        registry=actions_1,
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
        requests=requests_1,
        next_permission_request_id=lambda: "permission-persistent-001",
    )

    with pytest.raises(KeyError):
        observations_1.get(action.action_id)
    # 第五步：调用 _open_state 模拟程序重启。分别恢复 Action 和 pending，
    # 断言它们与原记录值相等，但不是原来的 Python 对象。
    actions_2, requests_2, decisions_2, observations_2 = _open_state(
        database_path
    )

    restored_action = actions_2.get(action.action_id)
    restored_pending = requests_2.get(pending.permission_request_id)

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

    decisions_2.record(user_decision)
    # 第七步：再次调用 _open_state 模拟第二次重启，只按决定 ID 恢复
    # 权威 Action 和 allowed 权限结论。
    actions_3, requests_3, decisions_3, observations_3 = _open_state(
        database_path
    )

    resumed_action, allowed = resolve_registered_permission_decision(
        user_decision.permission_decision_id,
        actions=actions_3,
        decisions=decisions_3,
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
        observations=observations_3,
    )
    # 第九步：第三次调用 _open_state，再按 action_id 恢复最终 Observation。
    actions_4, requests_4, decisions_4, observations_4 = _open_state(
        database_path
    )

    restored_observation = observations_4.get(action.action_id)

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

    assert actions_4.get(action.action_id) == action
    assert requests_4.get(pending.permission_request_id) == pending
    assert (
            decisions_4.get(user_decision.permission_decision_id)
            == user_decision
    )
