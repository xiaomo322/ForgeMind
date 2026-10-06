"""把 read_file Decision 连接到 SQLite Runtime 完整执行链。"""

from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.acceptance import (
    ActionIdFactory,
    accept_and_register_read_file_decision,
)
from forgemind.runtime.ids import new_action_id
from forgemind.runtime.read_file_execution import execute_read_file_action
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.decisions import ReadFileToolCallDecision
from forgemind.schema.observations import TerminalObservation
from forgemind.schema.tasks import TaskStatus
from forgemind.state.sqlite_state import SQLiteForgeMindState


class StaleReadFileDecisionError(RuntimeError):
    """模型返回后，任务状态已经不再允许执行该读取 Decision。"""

    def __init__(self, task_id: str, status: TaskStatus) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(
            f"任务 {task_id!r} 当前状态为 {status.value!r}，"
            "不能执行旧的 read_file Decision"
        )


@dataclass(frozen=True, slots=True)
class ReadFileHandlingResult:
    """同时保留 Runtime 接受的读取请求与实际读取终态。"""

    action: AcceptedReadFileToolAction
    observation: TerminalObservation


def handle_read_file_decision(
    decision: ReadFileToolCallDecision,
    *,
    task_id: str,
    state: SQLiteForgeMindState,
    next_action_id: ActionIdFactory = new_action_id,
) -> ReadFileHandlingResult:
    """重新校验任务后，接受、执行并持久化 read_file。"""

    # 第一步：读取最新任务视图；如果任务不再是 RUNNING，抛出
    # StaleReadFileDecisionError，且不能登记 Action。
    task_view = state.get_task_view(task_id)
    current_status = task_view.current_status.status
    if current_status is not TaskStatus.RUNNING:
        raise StaleReadFileDecisionError(
            task_id,
            current_status,
        )

    # 第二步：调用 accept_and_register_read_file_decision，把 decision、
    # task_id、state.actions 和 next_action_id 传入，保存权威 action。
    action = accept_and_register_read_file_decision(
        decision,
        task_id=task_id,
        registry=state.actions,
        next_action_id=next_action_id,
    )

    # 第三步：从 task_view.task.project_root 创建 Path，调用
    # execute_read_file_action，并把 state.observations 作为事实写入端。
    project_root = Path(task_view.task.project_root)
    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=state.observations,
    )
    # 第四步：返回 ReadFileHandlingResult(action, observation)。
    return ReadFileHandlingResult(
        action=action,
        observation=observation,
    )