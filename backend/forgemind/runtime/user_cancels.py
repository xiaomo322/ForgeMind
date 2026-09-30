"""把用户对当前询问的取消响应编排为任务终止。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.ids import new_task_status_id, new_user_response_id
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


IdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class UserCancelCancelledResult:
    """Runtime 已原子持久化的取消回答与终止状态。"""

    response: UserResponseRecord
    cancelled_status: TaskStatusRecord


def cancel_from_user_response(
    *,
    task_id: str,
    question_action_id: str,
    raw_response: str,
    cancellation_reason: str | None,
    state: SQLiteForgeMindState,
    next_response_id: IdFactory = new_user_response_id,
    next_task_status_id: IdFactory = new_task_status_id,
) -> UserCancelCancelledResult:
    """记录用户取消并原子把等待任务转为终态。"""

    current = state.task_statuses.get_current(task_id)
    response = UserResponseRecord(
        response_id=next_response_id(),
        task_id=task_id,
        question_action_id=question_action_id,
        response_type=UserResponseType.CANCEL,
        raw_response=raw_response,
        selected_option=None,
        cancellation_reason=cancellation_reason,
    )
    cancelled_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=TaskStatus.CANCELLED,
        reason="用户明确取消任务",
    )

    state.record_user_cancel_cancelled(response, cancelled_status)

    return UserCancelCancelledResult(
        response=response,
        cancelled_status=cancelled_status,
    )
