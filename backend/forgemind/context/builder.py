"""从完整 TaskStateView 构建单轮 Agent Task Context。"""

from forgemind.schema.context import AgentTaskContext
from forgemind.schema.tasks import TaskStateView


class InvalidActionContextLimitError(ValueError):
    """Action 上下文数量限制不是正整数。"""

    def __init__(self, value: object) -> None:
        self.value = value
        super().__init__(f"max_action_count 必须是正整数：{value!r}")


def build_agent_task_context(
    task_view: TaskStateView,
    *,
    max_action_count: int,
    max_message_count: int = 20,
) -> AgentTaskContext:
    """保留最近 Action，并显式报告被省略的历史数量。"""

    # 第一步：拒绝 bool、非 int 或小于 1 的 max_action_count，抛出
    # InvalidActionContextLimitError(max_action_count)。注意 bool 必须在
    # isinstance(value, int) 之外单独判断。
    if (
        isinstance(max_action_count, bool)
        or not isinstance(max_action_count, int)
        or max_action_count < 1
    ):
        raise InvalidActionContextLimitError(max_action_count)
    if isinstance(max_message_count, bool) or not isinstance(max_message_count, int) or max_message_count < 1:
        raise ValueError("max_message_count 必须是正整数")
    # 第二步：total_action_count = len(task_view.actions)。
    total_action_count = len(task_view.actions)
    # 第三步：recent_actions 取 task_view.actions 的最后
    # max_action_count 条；切片不能改变原元组中的 ActionStateView。
    recent_actions = task_view.actions[-max_action_count:]
    # 第四步：omitted_action_count = total - len(recent_actions)。
    omitted_action_count = total_action_count - len(recent_actions)

    # 第五步：构造并返回 AgentTaskContext：task 和 current_status 直接
    # 来自 task_view；完整标记等于 omitted_action_count == 0。
    applied_messages = tuple(item for item in task_view.messages if item.application is not None)
    recent_messages = applied_messages[-max_message_count:]
    omitted_message_count = len(applied_messages) - len(recent_messages)
    return AgentTaskContext(
        task=task_view.task,
        current_status=task_view.current_status,
        recent_actions=recent_actions,
        total_action_count=total_action_count,
        omitted_action_count=omitted_action_count,
        is_action_history_complete=omitted_action_count == 0,
        recent_messages=recent_messages,
        total_message_count=len(applied_messages),
        omitted_message_count=omitted_message_count,
        is_message_history_complete=omitted_message_count == 0,
    )
