"""把 edit_file Decision 转换为等待用户批准的 SQLite State。"""

from collections.abc import Callable
from dataclasses import dataclass

from forgemind.runtime.acceptance import (
    ActionIdFactory,
    accept_edit_file_decision,
)
from forgemind.runtime.ids import (
    new_action_id,
    new_permission_request_id,
    new_task_status_id,
)
from forgemind.runtime.permission_policy import check_edit_file_permission
from forgemind.runtime.permissions import (
    PermissionRequestIdFactory,
    build_pending_edit_file_permission_request,
)
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.decisions import EditFileToolCallDecision
from forgemind.schema.permissions import PendingEditFilePermissionRequest
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


TaskStatusIdFactory = Callable[[], str]


class StaleEditFileDecisionError(RuntimeError):
    """模型返回后，任务状态已经不再允许接受该修改 Decision。"""

    def __init__(self, task_id: str, status: TaskStatus) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(
            f"任务 {task_id!r} 当前状态为 {status.value!r}，"
            "不能接受旧的 edit_file Decision"
        )


@dataclass(frozen=True, slots=True)
class EditFilePermissionWaitingResult:
    """已经原子持久化的修改 Action、权限请求和等待状态。"""

    action: AcceptedEditFileToolAction
    permission_request: PendingEditFilePermissionRequest
    waiting_status: TaskStatusRecord


def handle_edit_file_decision(
    decision: EditFileToolCallDecision,
    *,
    task_id: str,
    state: SQLiteForgeMindState,
    next_action_id: ActionIdFactory = new_action_id,
    next_permission_request_id: PermissionRequestIdFactory = (
        new_permission_request_id
    ),
    next_task_status_id: TaskStatusIdFactory = new_task_status_id,
) -> EditFilePermissionWaitingResult:
    """接受修改决策并暂停任务；本阶段绝不执行 edit_file Tool。"""

    # 第一步：重新读取模型返回后的最新 State。只有 RUNNING 任务才能
    # 接受新 Action，旧 Decision 不能越过当前状态继续执行。
    task_view = state.get_task_view(task_id)
    current_status = task_view.current_status
    if current_status.status is not TaskStatus.RUNNING:
        raise StaleEditFileDecisionError(task_id, current_status.status)

    # 第二步：调用 accept_edit_file_decision()，由 Runtime 生成 action_id；
    # 此处只构造 Action，不能调用会单独登记 Action 的旧入口。
    action = accept_edit_file_decision(
        decision,
        task_id=task_id,
        next_action_id=next_action_id,
    )
    # 第三步：依次调用 check_edit_file_permission() 和
    # build_pending_edit_file_permission_request()，得到权限结论与完整请求。
    permission_check = check_edit_file_permission(action)
    permission_request = build_pending_edit_file_permission_request(
        action,
        permission_check,
        next_permission_request_id=next_permission_request_id,
    )

    # 第四步：构造 revision + 1 的 WAITING_USER 状态；状态编号来自工厂，
    # reason 使用权限检查的原因。
    waiting_status = TaskStatusRecord(
        task_status_id=next_task_status_id(),
        task_id=task_id,
        revision=current_status.revision + 1,
        status=TaskStatus.WAITING_USER,
        reason=permission_check.reason,
    )

    # 第五步：调用 state.record_tool_permission_waiting(...) 原子写入三项
    # 事实；成功后返回 EditFilePermissionWaitingResult。
    state.record_tool_permission_waiting(
        action,
        permission_request,
        waiting_status,
    )
    return EditFilePermissionWaitingResult(
        action=action,
        permission_request=permission_request,
        waiting_status=waiting_status,
    )
