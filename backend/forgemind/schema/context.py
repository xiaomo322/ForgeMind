"""提供给 Agent 单轮推理使用的严格、有限上下文契约。"""

from typing import Literal, Self

from pydantic import Field, model_validator

from forgemind.schema.base import StrictContractModel
from forgemind.schema.tasks import (
    ActionStateView,
    TaskRecord,
    TaskStatusRecord,
)


class AgentTaskContext(StrictContractModel):
    """保留任务核心事实，并明确声明 Action 历史是否被裁剪。"""

    task: TaskRecord
    current_status: TaskStatusRecord
    recent_actions: tuple[ActionStateView, ...]
    total_action_count: int = Field(ge=0)
    omitted_action_count: int = Field(ge=0)
    is_action_history_complete: bool

    @model_validator(mode="after")
    def require_consistent_history_window(self) -> Self:
        """裁剪元数据和保留的 Action 后缀必须彼此一致。"""

        # 第一步：检查 current_status.task_id 是否等于 task.task_id；
        # 不同则抛出 ValueError("当前状态不属于上下文任务")。
        if self.current_status.task_id != self.task.task_id:
            raise ValueError("当前状态不属于上下文任务")
        # 第二步：遍历 recent_actions，检查每条 action.task_id 是否等于
        # task.task_id；不同则抛出 ValueError("Action 不属于上下文任务")。
        for action_state in self.recent_actions:
            if action_state.action.task_id != self.task.task_id:
                raise ValueError("Action 不属于上下文任务")
        # 第三步：检查 total_action_count 是否等于 omitted_action_count 加
        # len(recent_actions)；不相等则抛出
        # ValueError("Action 历史数量不一致")。
        if self.total_action_count != (
            self.omitted_action_count + len(self.recent_actions)
        ):
            raise ValueError("Action 历史数量不一致")
        # 第四步：检查 is_action_history_complete 是否严格等于
        # (omitted_action_count == 0)；不一致则抛出
        # ValueError("Action 历史完整标记不一致")。
        if self.is_action_history_complete != (
            self.omitted_action_count == 0
        ):
            raise ValueError("Action 历史完整标记不一致")
        # 第五步：建立 expected_sequences：从 omitted_action_count + 1
        # 开始，到 total_action_count 结束；比较 recent_actions 的实际
        # sequence 元组。不一致则抛出
        # ValueError("保留的 Action 不是连续的最新后缀")。
        expected_sequences = tuple(
            range(
                self.omitted_action_count + 1,
                self.total_action_count + 1,
            )
        )
        actual_sequences = tuple(
            item.sequence for item in self.recent_actions
        )

        if actual_sequences != expected_sequences:
            raise ValueError("保留的 Action 不是连续的最新后缀")
        # 第六步：全部通过后返回 self。
        return self


class AgentContextEnvelope(StrictContractModel):
    """为序列化后的 Agent Context 提供稳定类型和版本标识。"""

    schema_version: Literal["0.1"] = "0.1"
    context_type: Literal["task_context"] = "task_context"
    context: AgentTaskContext
