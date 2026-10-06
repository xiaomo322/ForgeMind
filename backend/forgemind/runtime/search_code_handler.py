"""把 search_code Decision 连接到 SQLite Runtime 完整执行链。"""

from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.acceptance import (
    ActionIdFactory,
    accept_and_register_search_code_decision,
)
from forgemind.runtime.ids import new_action_id
from forgemind.runtime.search_code_execution import (
    execute_search_code_action,
)
from forgemind.schema.actions import AcceptedSearchCodeToolAction
from forgemind.schema.decisions import SearchCodeToolCallDecision
from forgemind.schema.observations import TerminalObservation
from forgemind.schema.tasks import TaskStatus
from forgemind.state.sqlite_state import SQLiteForgeMindState


class StaleSearchCodeDecisionError(RuntimeError):
    """模型返回后，任务状态已经不再允许执行该 Decision。"""

    def __init__(self, task_id: str, status: TaskStatus) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(
            f"任务 {task_id!r} 当前状态为 {status.value!r}，"
            "不能执行旧的 search_code Decision"
        )


@dataclass(frozen=True, slots=True)
class SearchCodeHandlingResult:
    """同时保留 Runtime 接受的请求与 Tool 产生的终态事实。"""

    action: AcceptedSearchCodeToolAction
    observation: TerminalObservation


def handle_search_code_decision(
    decision: SearchCodeToolCallDecision,
    *,
    task_id: str,
    state: SQLiteForgeMindState,
    next_action_id: ActionIdFactory = new_action_id,
) -> SearchCodeHandlingResult:
    """重新校验任务后，接受、执行并持久化 search_code。"""

    # 第一步：调用 state.get_task_view(task_id)，取得最新权威任务视图。
    task_view = state.get_task_view(task_id)
    current_status = task_view.current_status.status
    # 第二步：如果 current_status.status 不是 TaskStatus.RUNNING，抛出
    # StaleSearchCodeDecisionError(task_id, 当前状态)，不能登记 Action。
    if current_status is not TaskStatus.RUNNING:
        raise StaleSearchCodeDecisionError(
            task_id,
            current_status,
        )
    # 第三步：调用 accept_and_register_search_code_decision(...)；task_id、
    # state.actions 和 next_action_id 都要显式传入，保存返回的 action。
    action = accept_and_register_search_code_decision(
        decision,
        task_id=task_id,
        registry=state.actions,
        next_action_id=next_action_id,
    )

    # 第四步：从最新 task_view.task.project_root 建立 Path；调用
    # execute_search_code_action(action, project_root=..., observations=
    # state.observations)，保存返回的 observation。
    project_root = Path(task_view.task.project_root)
    observation = execute_search_code_action(
        action,
        project_root=project_root,
        observations=state.observations,
    )
    # 第五步：返回 SearchCodeHandlingResult(action, observation)。
    return SearchCodeHandlingResult(
        action=action,
        observation=observation,
    )
