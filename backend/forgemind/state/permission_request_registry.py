"""等待用户确认的权限请求注册表。"""

from forgemind.schema.permissions import PendingPermissionRequest
from forgemind.state.action_registry import InMemoryActionRegistry


class UnknownPermissionRequestActionError(ValueError):
    """待确认请求引用的 Action 尚未注册。"""


class DuplicatePermissionRequestIdError(ValueError):
    """permission_request_id 已经指向另一条询问记录。"""


class PermissionRequestActionSnapshotMismatchError(ValueError):
    """待确认请求保存的操作快照与权威 Action 不一致。"""


class InMemoryPermissionRequestRegistry:
    """V0.1 单进程内存待确认权限请求注册表。"""

    def __init__(self, actions: InMemoryActionRegistry) -> None:
        self._actions = actions
        self._requests: dict[str, PendingPermissionRequest] = {}

    def register(self, request: PendingPermissionRequest) -> None:
        """登记请求；未知 Action、快照变化或重复编号都明确失败。"""

        try:
            action = self._actions.get(request.action_id)
        except KeyError:
            # State 不保存无法追溯到权威 Action 的孤立权限询问。
            raise UnknownPermissionRequestActionError(request.action_id) from None

        # 即使 action_id 相同，也必须核对任务和完整参数。否则调用方可
        # 借用旧 Action 编号，向用户展示或批准另一项实际操作。
        if (
            request.task_id != action.task_id
            or request.action_type != action.action_type
            or request.tool_name != action.tool_name
            or request.arguments != action.arguments
        ):
            raise PermissionRequestActionSnapshotMismatchError(request.action_id)

        # 注册表只追加新事实，绝不覆盖已经展示给用户的原始询问。
        if request.permission_request_id in self._requests:
            raise DuplicatePermissionRequestIdError(request.permission_request_id)

        self._requests[request.permission_request_id] = request

    def get(self, permission_request_id: str) -> PendingPermissionRequest:
        """按询问编号取得待确认请求。"""

        return self._requests[permission_request_id]
