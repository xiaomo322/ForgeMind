from collections.abc import Callable

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.decisions import ReadFileToolCallDecision


ActionIdFactory = Callable[[], str]


def accept_read_file_decision(
    decision: ReadFileToolCallDecision,
    *,
    task_id: str,
    next_action_id: ActionIdFactory,
) -> AcceptedReadFileToolAction:
    """把已校验的 read_file 决策转换为 Runtime 权威 Action。"""

    # ID 生成策略由 Runtime 外层注入。这里不读取 Agent 输出中的编号，
    # 也不把 UUID、数据库序列等具体方案写死在转换函数里。
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
