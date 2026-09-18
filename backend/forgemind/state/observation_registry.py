from forgemind.schema.observations import TerminalObservation
from forgemind.state.action_registry import InMemoryActionRegistry


class UnknownActionIdError(ValueError):
    """Observation 引用的 action_id 尚未注册。"""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"找不到 Observation 对应的 Action：{action_id}")


class DuplicateObservationError(ValueError):
    """同一 Action 已存在终态 Observation。"""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"Action 已存在 Observation：{action_id}")


class InMemoryObservationRegistry:
    """V0.1 单进程内存 Observation 注册表。"""

    def __init__(self, actions: InMemoryActionRegistry) -> None:
        self._actions = actions
        self._observations: dict[str, TerminalObservation] = {}

    def record(self, observation: TerminalObservation) -> None:
        """为已注册 Action 记录唯一终态事实。"""

        # 先确认来源 Action 存在。get 找不到时抛出的错误不能被吞掉，
        # 否则 State 会出现无法追溯到请求的孤立 Observation。
        try:
            self._actions.get(observation.action_id)
        except KeyError:
            raise UnknownActionIdError(observation.action_id) from None

        # 一个 Action 在 V0.1 只允许一个终态 Observation。重复结果不能
        # 覆盖首次记录，否则实际发生过的拒绝或失败会从历史中消失。
        if observation.action_id in self._observations:
            raise DuplicateObservationError(observation.action_id)

        self._observations[observation.action_id] = observation

    def get(self, action_id: str) -> TerminalObservation:
        """按 action_id 取得该 Action 的终态 Observation。"""

        return self._observations[action_id]
