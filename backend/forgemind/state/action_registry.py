from forgemind.schema.actions import AcceptedReadFileToolAction


class DuplicateActionIdError(ValueError):
    """注册表中已经存在相同 action_id。"""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"action_id 已存在：{action_id}")


class InMemoryActionRegistry:
    """V0.1 单进程内存 Action 注册表。"""

    def __init__(self) -> None:
        self._actions: dict[str, AcceptedReadFileToolAction] = {}

    def register(self, action: AcceptedReadFileToolAction) -> None:
        """注册新 Action；重复编号时保留原记录并明确失败。"""

        # 不能使用普通赋值直接覆盖。一个 action_id 必须永远指向同一份
        # 权威请求，否则历史 Observation 和授权会关联到错误内容。
        if action.action_id in self._actions:
            raise DuplicateActionIdError(action.action_id)

        self._actions[action.action_id] = action

    def get(self, action_id: str) -> AcceptedReadFileToolAction:
        """按权威编号取得已注册 Action。"""

        return self._actions[action_id]
