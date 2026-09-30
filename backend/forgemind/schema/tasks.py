"""任务创建时不可覆盖的来源事实。"""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator

from forgemind.schema.actions import AcceptedAction
from forgemind.schema.base import StrictContractModel
from forgemind.schema.observations import TerminalObservation
from forgemind.schema.permissions import (
    PendingPermissionRequest,
    PermissionDecisionRecord,
)


class TaskRecord(StrictContractModel):
    """由 Runtime 建立的任务身份、用户原话和项目边界。"""

    task_id: str = Field(min_length=1)
    original_request: str = Field(min_length=1)
    project_root: str = Field(min_length=1)

    @field_validator("task_id", "original_request", "project_root")
    @classmethod
    def require_visible_text(cls, value: str) -> str:
        """拒绝只有空白符的必填文本，同时保留用户原始内容。"""

        # 第一步：使用 value.strip() 判断内容是否只包含空格、换行等空白。
        if not value.strip():
            # 第二步：如果清理后为空，抛出 ValueError；不要返回清理后的字符串，
            # 因为 original_request 必须保留用户输入的原始内容。
            raise ValueError("必填文本不能只包含空白字符")
        # 第三步：校验通过后原样返回 value。
        return value

    @field_validator("project_root")
    @classmethod
    def require_absolute_project_root(cls, project_root: str) -> str:
        """任务必须绑定 Runtime 已解析的绝对项目根目录。"""

        # 第一步：使用 Path(project_root).is_absolute() 检查绝对路径。
        if not Path(project_root).is_absolute():
            # 第二步：相对路径抛出 ValueError，绝对路径原样返回。
            raise ValueError("project_root 必须是绝对路径")

        return project_root


class TaskStatus(StrEnum):
    """任务级生命周期状态；工具失败本身不会直接终止任务。"""

    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskStatusRecord(StrictContractModel):
    """一次不可覆盖的任务状态事实。"""

    task_status_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    status: TaskStatus
    reason: str = Field(min_length=1)


class ActionStateView(StrictContractModel):
    """一条有序 AcceptedAction 及其可能尚不存在的终态结果。"""

    sequence: int = Field(ge=1)
    action: AcceptedAction
    permission_request: PendingPermissionRequest | None
    permission_decision: PermissionDecisionRecord | None
    observation: TerminalObservation | None

    @model_validator(mode="after")
    def require_matching_observation(self) -> Self:
        """权限链和 Observation 必须属于这一条 Action。"""

        # 第一步：如果 self.action.action_type == "ask_user"，检查
        # permission_request 和 permission_decision 是否都为 None；否则抛出
        # ValueError("AskUser Action 不能包含 Tool 权限记录")。
        if self.action.action_type == "ask_user":
            if (
                self.permission_decision is not None
                or self.permission_request is not None
            ):
                raise ValueError(
                    "AskUser Action 不能包含 Tool 权限记录"
                )
            # 接着检查 observation 是否为 None；否则抛出
            # ValueError("AskUser Action 不能包含 Tool Observation")。
            # 三项都为 None 时立即 return self，不能继续访问 Tool 专属字段。
            if self.observation is not None:
                raise ValueError(
                    "AskUser Action 不能包含 Tool Observation"
                )
            return self

        # 第二步：如果 permission_request 不为 None，检查它的 task_id、
        # action_id、action_type、tool_name 和 arguments 是否分别等于
        # self.action 中的对应字段；任一不同就抛出
        # ValueError("权限请求不属于对应的 Action")。
        if self.permission_request is not None:
            if (
                self.permission_request.task_id != self.action.task_id
                or self.permission_request.action_id
                != self.action.action_id
                or self.permission_request.action_type
                != self.action.action_type
                or self.permission_request.tool_name
                != self.action.tool_name
                or self.permission_request.arguments
                != self.action.arguments
            ):
                raise ValueError("权限请求不属于对应的 Action")
        # 第三步：如果 permission_decision 不为 None，但
        # permission_request 为 None，抛出
        # ValueError("权限决定缺少对应的权限请求")。
        if (
            self.permission_decision is not None
            and self.permission_request is None
        ):
            raise ValueError("权限决定缺少对应的权限请求")
        # 第四步：如果两者都存在，检查决定的 permission_request_id、
        # task_id、action_id 是否与请求及 Action 一致；任一不同就抛出
        # ValueError("权限决定不属于对应的权限请求")。
        if (
            self.permission_decision is not None
            and self.permission_request is not None
            and (
                self.permission_decision.permission_request_id
                != self.permission_request.permission_request_id
                or self.permission_decision.task_id != self.action.task_id
                or self.permission_decision.action_id
                != self.action.action_id
            )
        ):
            raise ValueError("权限决定不属于对应的权限请求")
        # 第五步：判断 self.observation 是否不为 None。
        # 第六步：仅在 Observation 存在时，比较它的 action_id 与
        # self.action.action_id。
        if (
            self.observation is not None
            and self.observation.action_id != self.action.action_id
        ):
            # 第七步：编号不相同时抛出 ValueError。
            raise ValueError("Observation 不属于对应的 Action")
        # 第八步：全部检查通过后返回 self。
        return self


class TaskStateView(StrictContractModel):
    """提供给 Runtime/Context Builder 的任务来源与当前生命周期视图。"""

    task: TaskRecord
    current_status: TaskStatusRecord
    # 这个字段故意不提供默认值：State 构建视图时必须明确说明已经查询
    # Action 历史；没有 Action 应传入空元组，而不是遗漏字段。
    actions: tuple[ActionStateView, ...]

    @model_validator(mode="after")
    def require_same_task(self) -> Self:
        """当前状态必须属于视图中的同一个任务。"""

        # 第一步：比较 self.current_status.task_id 与 self.task.task_id。
        if self.current_status.task_id != self.task.task_id:
            raise ValueError("当前状态不属于视图中的任务")

        # 第二步：使用 enumerate(self.actions, start=1) 同时取得
        # expected_sequence 和 action_record。
        for expected_sequence, action_state in enumerate(
            self.actions,
            start=1,
        ):
            # 第三步：检查 action_state.action.task_id 是否等于
            # self.task.task_id；不同就抛出 ValueError。
            if action_state.action.task_id != self.task.task_id:
                raise ValueError("Action 不属于视图中的任务")
            # 第四步：检查 action_state.sequence 是否等于 expected_sequence；
            # 不同就抛出 ValueError。
            if action_state.sequence != expected_sequence:
                raise ValueError("Action 序号必须从 1 开始连续递增")
        # 第五步：全部检查通过后返回 self。
        return self
