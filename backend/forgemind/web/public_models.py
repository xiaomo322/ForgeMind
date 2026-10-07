"""只包含浏览器需要信息的公开 Task State 视图。"""

from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.tasks import TaskStateView, TaskStatus


class PublicActionState(StrictContractModel):
    """一条 Action 以及已持久化的交互、权限和执行结果。"""

    sequence: int = Field(ge=1)
    action: dict[str, Any]
    user_response: dict[str, Any] | None
    permission_request: dict[str, Any] | None
    permission_decision: dict[str, Any] | None
    observation: dict[str, Any] | None


class PublicTaskState(StrictContractModel):
    """页面刷新时恢复任务所需的公开状态，不包含服务器绝对路径。"""

    task_id: str = Field(min_length=1)
    original_request: str = Field(min_length=1)
    status: TaskStatus
    revision: int = Field(ge=1)
    actions: tuple[PublicActionState, ...]


def build_public_task_state(view: TaskStateView) -> PublicTaskState:
    """从 Runtime 权威视图投影出不会泄露 project_root 的 Web 模型。"""

    actions = tuple(
        PublicActionState(
            sequence=item.sequence,
            action=jsonable_encoder(item.action),
            user_response=(
                jsonable_encoder(item.user_response)
                if item.user_response is not None
                else None
            ),
            permission_request=(
                jsonable_encoder(item.permission_request)
                if item.permission_request is not None
                else None
            ),
            permission_decision=(
                jsonable_encoder(item.permission_decision)
                if item.permission_decision is not None
                else None
            ),
            observation=(
                jsonable_encoder(item.observation)
                if item.observation is not None
                else None
            ),
        )
        for item in view.actions
    )
    return PublicTaskState(
        task_id=view.task.task_id,
        original_request=view.task.original_request,
        status=view.current_status.status,
        revision=view.current_status.revision,
        actions=actions,
    )
