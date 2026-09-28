"""由 Runtime 执行确定性的任务状态转换检查。"""

from collections.abc import Callable
from typing import Protocol

from forgemind.schema.tasks import TaskStatus, TaskStatusRecord


class InvalidTaskStatusTransitionError(ValueError):
    """当前状态不能直接转换到目标状态。"""

    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"非法任务状态转换：{current} -> {target}")


# 第一步：填写允许转换表。
# RUNNING 可以进入 WAITING_USER、COMPLETED、BLOCKED、CANCELLED。
# WAITING_USER 收到回答后只能恢复 RUNNING，或进入 BLOCKED、CANCELLED；
# 回答本身不能绕过重新判断而直接把任务标为 COMPLETED。
# COMPLETED、BLOCKED、CANCELLED 都是终态，没有下一状态。
_ALLOWED_TASK_STATUS_TRANSITIONS: dict[
    TaskStatus,
    frozenset[TaskStatus],
] = {
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_USER,
            TaskStatus.COMPLETED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_USER: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.BLOCKED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def require_task_status_transition(
    current: TaskStatus,
    target: TaskStatus,
) -> None:
    """允许合法转换；非法转换抛出包含起止状态的稳定错误。"""

    # 第二步：从转换表取得 current 对应的允许目标集合。
    allowed_targets = _ALLOWED_TASK_STATUS_TRANSITIONS[current]
    # 第三步：如果 target 不在集合中，抛出
    # InvalidTaskStatusTransitionError(current, target)。
    if target not in allowed_targets:
        raise InvalidTaskStatusTransitionError(current, target)
    # 合法时不需要返回新状态；调用方继续创建 TaskStatusRecord。


class TaskStatusRegistry(Protocol):
    """Runtime 推进状态所需的最小 State 接口。"""

    def get_current(self, task_id: str) -> TaskStatusRecord: ...

    def record(self, status_record: TaskStatusRecord) -> None: ...


def transition_task_status(
    task_id: str,
    target: TaskStatus,
    reason: str,
    *,
    statuses: TaskStatusRegistry,
    next_task_status_id: Callable[[], str],
) -> TaskStatusRecord:
    """从 State 当前版本构造、登记并返回下一条权威状态。"""

    # 第一步：调用 statuses.get_current(task_id) 取得当前权威记录。
    current = statuses.get_current(task_id)

    # 第二步：构造 TaskStatusRecord：编号来自 next_task_status_id()，
    # task_id/reason/target 来自参数，revision 为当前 revision + 1。
    next_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current.revision + 1,
        status=target,
        reason=reason,
    )

    # 第三步：先调用 statuses.record(next_status)，成功后再返回它。
    # Registry 会再次检查 revision 和状态转换，防止并发写入越过规则。
    statuses.record(next_status)
    return next_status
