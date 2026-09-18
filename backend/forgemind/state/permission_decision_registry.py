"""用户权限决定的内存注册表。"""

from forgemind.schema.permissions import PermissionDecisionRecord
from forgemind.state.permission_request_registry import (
    InMemoryPermissionRequestRegistry,
)


class UnknownPermissionRequestIdError(ValueError):
    """决定引用的 permission_request_id 不存在。"""


class PermissionDecisionRequestMismatchError(ValueError):
    """决定的任务或 Action 与待确认请求不一致。"""


class DuplicatePermissionDecisionIdError(ValueError):
    """permission_decision_id 已经指向一条决定记录。"""


class DuplicatePermissionRequestDecisionError(ValueError):
    """同一待确认请求已经存在最终用户决定。"""


class InMemoryPermissionDecisionRegistry:
    """V0.1 单进程内存 PermissionDecision 注册表。"""

    def __init__(self, requests: InMemoryPermissionRequestRegistry) -> None:
        self._requests = requests
        self._by_id: dict[str, PermissionDecisionRecord] = {}
        self._by_request_id: dict[str, PermissionDecisionRecord] = {}

    def record(self, decision: PermissionDecisionRecord) -> None:
        """校验引用后追加决定，任何已有事实都不被覆盖。"""

        try:
            request = self._requests.get(decision.permission_request_id)
        except KeyError:
            # 没有原始询问就无法知道用户批准或拒绝了什么范围。
            raise UnknownPermissionRequestIdError(
                decision.permission_request_id
            ) from None

        # permission_request_id 正确仍不够；任务和 Action 也必须一致，
        # 避免调用方把一条回答重新标记后应用到另一任务或操作。
        if (
            decision.task_id != request.task_id
            or decision.action_id != request.action_id
        ):
            raise PermissionDecisionRequestMismatchError(
                decision.permission_request_id
            )

        if decision.permission_decision_id in self._by_id:
            raise DuplicatePermissionDecisionIdError(
                decision.permission_decision_id
            )

        # 一个询问只能有一个最终用户决定。第二条相反决定不能覆盖
        # 第一条，否则 Runtime 将无法确定用户当时真正选择了什么。
        if decision.permission_request_id in self._by_request_id:
            raise DuplicatePermissionRequestDecisionError(
                decision.permission_request_id
            )

        self._by_id[decision.permission_decision_id] = decision
        self._by_request_id[decision.permission_request_id] = decision

    def get(self, permission_decision_id: str) -> PermissionDecisionRecord:
        """按决定编号取得记录。"""

        return self._by_id[permission_decision_id]

    def get_for_request(
        self,
        permission_request_id: str,
    ) -> PermissionDecisionRecord:
        """取得一条待确认请求对应的最终决定。"""

        return self._by_request_id[permission_request_id]
