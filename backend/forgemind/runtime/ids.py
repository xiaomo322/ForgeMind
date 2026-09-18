from uuid import uuid4


def new_action_id() -> str:
    """生成供 Runtime 使用的 Action 标识。"""

    # 前缀让日志中的对象类型更容易辨认；UUID4 负责生成高概率唯一值。
    # 最终是否与已有记录冲突，仍需由 State/持久化层检查。
    return f"action_{uuid4()}"
