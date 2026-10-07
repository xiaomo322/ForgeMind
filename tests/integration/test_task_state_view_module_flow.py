from pathlib import Path

from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    RejectedObservation,
)
from forgemind.schema.permissions import (
    PendingRunCommandPermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.run_command import RunCommandArguments
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _action(action_id: str) -> AcceptedRunCommandToolAction:
    """建立一条只用于 State 模块测试的不可变命令 Action。"""

    return AcceptedRunCommandToolAction(
        action_id=action_id,
        task_id="task-module-flow",
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-V",),
            working_directory=".",
            timeout_seconds=30,
        ),
        reason=f"模块测试动作 {action_id}",
    )


def _request(
    action: AcceptedRunCommandToolAction,
) -> PendingRunCommandPermissionRequest:
    """为指定 Action 建立完整且范围不变的权限请求快照。"""

    return PendingRunCommandPermissionRequest(
        permission_request_id=f"permission-{action.action_id}",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments,
        reason="命令执行需要用户确认",
        basis_ids=("policy-command-001",),
    )


def _decision(
    request: PendingRunCommandPermissionRequest,
) -> PermissionDecisionRecord:
    """记录用户对指定权限请求作出的拒绝决定。"""

    return PermissionDecisionRecord(
        permission_decision_id=f"decision-{request.action_id}",
        permission_request_id=request.permission_request_id,
        task_id=request.task_id,
        action_id=request.action_id,
        decision=PermissionDecision.REJECT,
        source="user",
        raw_response="拒绝执行这个命令",
    )


def _rejected(action_id: str) -> RejectedObservation:
    """建立 Tool 调用前因用户拒绝而产生的终态 Observation。"""

    return RejectedObservation(
        action_id=action_id,
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户拒绝执行命令",
        ),
    )


def test_task_state_view_recovers_complete_action_history(
    tmp_path: Path,
) -> None:
    """跨重启恢复无请求、等待回答和已拒绝三种 Action 状态。"""

    # 第一步：建立 database_path 和 first_state；创建 TaskRecord 与
    # revision=1、RUNNING 的 TaskStatusRecord，并用 create_task 原子登记。
    database_path = tmp_path / "state.db"
    first_state = SQLiteForgeMindState.open(database_path)
    task = TaskRecord(
        task_id="task-module-flow",
        original_request="验证完整任务视图恢复",
        project_root=str(tmp_path.resolve()),
    )
    initial_status = TaskStatusRecord(
        task_status_id="status-module-flow-001",
        task_id=task.task_id,
        revision=1,
        status=TaskStatus.RUNNING,
        reason="任务创建",
    )
    first_state.create_task(task, initial_status)

    # 第二步：分别建立 action_1、action_2、action_3，按照这个顺序调用
    # first_state.actions.register(...) 登记。
    action_1 = _action("action-001")
    action_2 = _action("action-002")
    action_3 = _action("action-003")
    for action in (action_1, action_2, action_3):
        first_state.actions.register(action)

    # 第三步：为 action_2 建立 waiting_request 并登记，但不建立决定和
    # Observation，表达“正在等待用户回答”。
    waiting_request = _request(action_2)
    first_state.permission_requests.register(waiting_request)

    # 第四步：为 action_3 建立 rejected_request 并登记；再建立
    # rejected_decision 和 rejected_observation，分别写入权限决定与
    # Observation Registry。
    rejected_request = _request(action_3)
    first_state.permission_requests.register(rejected_request)
    rejected_decision = _decision(rejected_request)
    first_state.permission_decisions.record(rejected_decision)
    rejected_observation = _rejected(action_3.action_id)
    first_state.observations.record(rejected_observation)

    # 第五步：重新调用 SQLiteForgeMindState.open(database_path)，保存为
    # restarted_state；调用 get_task_view(task.task_id) 得到 restored。
    restarted_state = SQLiteForgeMindState.open(database_path)
    restored = restarted_state.get_task_view(task.task_id)

    # -s 会关闭 pytest 的 stdout 捕获，因此这些内容会显示在终端中。
    print(
        "\n恢复任务："
        f"task_id={restored.task.task_id}, "
        f"status={restored.current_status.status.value}"
    )
    for action_state in restored.actions:
        request_status = (
            "none"
            if action_state.permission_request is None
            else action_state.permission_request.status
        )
        decision_status = (
            "none"
            if action_state.permission_decision is None
            else action_state.permission_decision.decision.value
        )
        observation_status = (
            "none"
            if action_state.observation is None
            else action_state.observation.status
        )
        print(
            f"sequence={action_state.sequence}, "
            f"action_id={action_state.action.action_id}, "
            f"request={request_status}, "
            f"decision={decision_status}, "
            f"observation={observation_status}"
        )

    first_action_state = restored.actions[0]
    waiting_action_state = restored.actions[1]
    rejected_action_state = restored.actions[2]

    # 第六步：断言 restored.task == task、restored.current_status ==
    # initial_status，并断言 restored.task is not task，证明来自磁盘恢复。
    assert restored.task == task
    assert restored.current_status == initial_status
    assert restored.task is not task

    # 第七步：断言三个 restored.actions 的 sequence 依次为 [1, 2, 3]，
    # action 依次等于 action_1、action_2、action_3。
    assert [item.sequence for item in restored.actions] == [1, 2, 3]
    assert [item.action for item in restored.actions] == [
        action_1,
        action_2,
        action_3,
    ]

    # 第八步：分别断言三条历史：
    # action_1 的 request/decision/observation 全为 None；
    # action_2 的 request 等于 waiting_request，其余两个为 None；
    # action_3 的 request、decision、observation 分别等于对应原记录。
    assert first_action_state.permission_request is None
    assert first_action_state.permission_decision is None
    assert first_action_state.observation is None

    assert waiting_action_state.permission_request == waiting_request
    assert waiting_action_state.permission_decision is None
    assert waiting_action_state.observation is None

    assert rejected_action_state.permission_request == rejected_request
    assert rejected_action_state.permission_decision == rejected_decision
    assert rejected_action_state.observation == rejected_observation

