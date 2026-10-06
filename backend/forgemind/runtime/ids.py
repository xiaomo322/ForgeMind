from uuid import uuid4


def new_action_id() -> str:
    """生成供 Runtime 使用的 Action 标识。"""

    # 前缀让日志中的对象类型更容易辨认；UUID4 负责生成高概率唯一值。
    # 最终是否与已有记录冲突，仍需由 State/持久化层检查。
    return f"action_{uuid4()}"


def new_task_status_id() -> str:
    """生成供 Runtime 使用的任务状态记录标识。"""

    return f"task_status_{uuid4()}"


def new_permission_request_id() -> str:
    """生成供 Runtime 使用的权限请求标识。"""

    return f"permission_request_{uuid4()}"


def new_permission_decision_id() -> str:
    """生成供 Runtime 使用的用户权限决定标识。"""

    return f"permission_decision_{uuid4()}"


def new_user_response_id() -> str:
    """生成供 Runtime 使用的用户回答标识。"""

    return f"user_response_{uuid4()}"
