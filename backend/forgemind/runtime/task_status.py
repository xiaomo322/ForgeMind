"""由 Runtime 执行确定性的任务状态转换检查。"""

from forgemind.schema.tasks import TaskStatus


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
