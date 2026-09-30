"""接受 AskUserDecision 并把任务原子推进到等待用户。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.acceptance import accept_ask_user_decision
from forgemind.runtime.ids import new_action_id, new_task_status_id
from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.decisions import AskUserDecision
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


IdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class AskUserWaitingResult:
    """Runtime 已持久化的询问 Action 与等待状态。"""

    action: AcceptedAskUserAction
    waiting_status: TaskStatusRecord


def accept_ask_user_and_wait(
    decision: AskUserDecision,
    *,
    task_id: str,
    state: SQLiteForgeMindState,
    next_action_id: IdFactory = new_action_id,
    next_task_status_id: IdFactory = new_task_status_id,
) -> AskUserWaitingResult:
    """接受询问决策，原子保存 Action 并暂停 Agent 循环。"""

    # 第一步：调用 state.task_statuses.get_current(task_id)，保存为 current。
    current = state.task_statuses.get_current(task_id)
    # 第二步：调用 accept_ask_user_decision；传入 decision、task_id 和
    # next_action_id，保存返回的 AcceptedAskUserAction 为 action。
    action = accept_ask_user_decision(
        decision,
        task_id=task_id,
        next_action_id=next_action_id,
    )
    # 第三步：构造 TaskStatusRecord，字段如下：
    # task_status_id 来自 next_task_status_id()；task_id 使用参数；
    # revision=current.revision + 1；status=TaskStatus.WAITING_USER；
    # reason 使用 decision.reason。保存为 waiting_status。
    waiting_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.WAITING_USER,
        reason=decision.reason,
    )

    # 第四步：调用 state.record_ask_user_waiting(action, waiting_status)。
    # 只有该原子写入成功后才能返回结果。
    state.record_ask_user_waiting(
        action,
        waiting_status,
    )

    # 第五步：构造并返回 AskUserWaitingResult，填入 action 和
    # waiting_status。
    return AskUserWaitingResult(
        action=action,
        waiting_status=waiting_status,
    )
