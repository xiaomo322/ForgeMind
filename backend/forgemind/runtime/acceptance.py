from collections.abc import Callable

from forgemind.runtime.ids import new_action_id
from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
    AcceptedSearchCodeToolAction,
)
from forgemind.schema.decisions import (
    ReadFileToolCallDecision,
    SearchCodeToolCallDecision,
)
from forgemind.state.action_registry import (
    DuplicateActionIdError,
    InMemoryActionRegistry,
)


ActionIdFactory = Callable[[], str]


class ActionIdAllocationError(RuntimeError):
    """Runtime 在限定次数内无法取得可注册的 action_id。"""

    def __init__(self, attempts: int) -> None:
        self.attempts = attempts
        super().__init__(f"连续 {attempts} 次生成了重复 action_id")


def accept_read_file_decision(
    decision: ReadFileToolCallDecision,
    *,
    task_id: str,
    next_action_id: ActionIdFactory = new_action_id,
) -> AcceptedReadFileToolAction:
    """把已校验的 read_file 决策转换为 Runtime 权威 Action。"""

    # 默认使用 Runtime 的 UUID 生成器；测试或未来数据库实现可以显式
    # 注入替代函数。这里永远不读取 Agent 输出中的编号。
    action_id = next_action_id()

    # decision 与 arguments 已不可变，可以安全复用嵌套对象；新 Action
    # 增加 Runtime 权威字段，但不覆盖或修改 Agent 原始决策。
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id=task_id,
        action_type=decision.action_type,
        tool_name=decision.tool_name,
        arguments=decision.arguments,
        reason=decision.reason,
    )


def accept_and_register_read_file_decision(
    decision: ReadFileToolCallDecision,
    *,
    task_id: str,
    registry: InMemoryActionRegistry,
    next_action_id: ActionIdFactory = new_action_id,
    max_id_attempts: int = 3,
) -> AcceptedReadFileToolAction:
    """接受并注册 read_file 决策；编号冲突时有限重试。"""

    for _ in range(max_id_attempts):
        action = accept_read_file_decision(
            decision,
            task_id=task_id,
            next_action_id=next_action_id,
        )

        try:
            # 注册表执行最终的“查重并写入”。只有注册成功的 Action
            # 才能返回给后续权限检查与 Tool 执行流程。
            registry.register(action)
        except DuplicateActionIdError:
            # 只对编号碰撞重试；参数错误或生成器故障必须原样暴露，
            # 避免把真正问题伪装成一次普通碰撞。
            continue

        return action

    # 必须设置上限，防止错误生成器一直返回同一个编号导致死循环。
    raise ActionIdAllocationError(max_id_attempts)


def accept_search_code_decision(
    decision: SearchCodeToolCallDecision,
    *,
    task_id: str,
    next_action_id: ActionIdFactory = new_action_id,
) -> AcceptedSearchCodeToolAction:
    """把已校验的 search_code 决策转换为 Runtime 权威 Action。"""

    # 第一步：调用 Runtime 的编号工厂取得 action_id，不能从 Decision 读取。
    action_id = next_action_id()
    # 第二步：构造 AcceptedSearchCodeToolAction，增加 action_id 和 task_id。
    # 第三步：原样保留已校验的路由标签、arguments 对象和 reason 后返回。
    return AcceptedSearchCodeToolAction(
        action_id=action_id,
        task_id=task_id,
        action_type=decision.action_type,
        tool_name=decision.tool_name,
        arguments=decision.arguments,
        reason=decision.reason,
    )


def accept_and_register_search_code_decision(
    decision: SearchCodeToolCallDecision,
    *,
    task_id: str,
    registry: InMemoryActionRegistry,
    next_action_id: ActionIdFactory = new_action_id,
    max_id_attempts: int = 3,
) -> AcceptedSearchCodeToolAction:
    """接受并注册 search_code 决策；编号冲突时有限重试。"""

    for _ in range(max_id_attempts):
        action = accept_search_code_decision(
            decision,
            task_id=task_id,
            next_action_id=next_action_id,
        )
        try:
            registry.register(action)
        except DuplicateActionIdError:
            continue
        return action

    raise ActionIdAllocationError(max_id_attempts)
