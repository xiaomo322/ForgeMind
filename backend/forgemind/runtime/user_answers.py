"""把应用收到的用户回答编排为权威 State 更新。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.ids import new_task_status_id, new_user_response_id
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


IdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class UserAnswerRunningResult:
    """Runtime 已原子持久化的回答与恢复状态。"""

    response: UserResponseRecord
    running_status: TaskStatusRecord


def resume_from_user_answer(
    *,
    task_id: str,
    question_action_id: str,
    raw_response: str,
    selected_option: str | None,
    state: SQLiteForgeMindState,
    next_response_id: IdFactory = new_user_response_id,
    next_task_status_id: IdFactory = new_task_status_id,
) -> UserAnswerRunningResult:
    """记录有效用户回答并原子恢复 Agent 循环。"""

    # 第一步：调用 state.task_statuses.get_current(task_id)，
    # 把当前权威状态保存为 current。高层用它计算下一个
    # revision，底层事务还会重新读取并核对，防止并发变化。

    # 第二步：构造 UserResponseRecord：
    # response_id 来自 next_response_id()；task_id、question_action_id、
    # raw_response、selected_option 来自函数参数；response_type 固定
    # 为 UserResponseType.ANSWER；cancellation_reason 固定为 None。

    # 第三步：构造 TaskStatusRecord：
    # task_status_id 来自 next_task_status_id()；task_id 来自参数；
    # revision=current.revision + 1；status=TaskStatus.RUNNING；
    # reason="已收到有效用户回答"。

    # 第四步：调用 state.record_user_answer_running(response,
    # running_status)。只有该原子方法成功返回后，才能对外
    # 声称回答和 RUNNING 状态已持久化。

    # 第五步：构造并返回 UserAnswerRunningResult，填入
    # response 和 running_status。
    current = state.task_statuses.get_current(task_id)

    response = UserResponseRecord(
        response_id=next_response_id(),
        task_id=task_id,
        question_action_id=question_action_id,
        response_type=UserResponseType.ANSWER,
        raw_response=raw_response,
        selected_option=selected_option,
        cancellation_reason=None,
    )
    running_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.RUNNING,
        reason="已收到有效用户回答",
    )

    state.record_user_answer_running(response, running_status)

    return UserAnswerRunningResult(
        response=response,
        running_status=running_status,
    )
