"""ForgeMind 的多轮应用服务；CLI 和未来 Web API 共用这一层。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import sys
from uuid import uuid4
from typing import Any

from forgemind.agent.loop import AgentLoopStepResult, run_agent_loop_step
from forgemind.agent.turn import AgentModel
from forgemind.runtime.handlers import build_runtime_handlers
from forgemind.runtime.ids import new_task_id, new_task_status_id
from forgemind.runtime.permission_approvals import (
    approve_edit_file_permission,
    resume_edit_execution,
)
from forgemind.runtime.permission_execution import approve_process_permission
from forgemind.runtime.permission_rejections import reject_permission_request
from forgemind.runtime.user_answers import resume_from_user_answer
from forgemind.schema.decisions import AgentDecisionParseFailure
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
)
from forgemind.schema.tasks import (
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.schema.messages import TaskMessageApplicationRecord, TaskMessageRecord


IdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class ApplicationRunResult:
    """一次连续驱动停止时的可观测结果。"""

    task_id: str
    status: TaskStatus
    steps_executed: int
    parse_failure: AgentDecisionParseFailure | None = None
    last_step: AgentLoopStepResult[object] | None = None


@dataclass(slots=True)
class ForgeMindApplication:
    """从权威 SQLite State 驱动 Agent、Runtime 和用户交互。"""

    state: SQLiteForgeMindState
    model: AgentModel
    max_action_count: int = 20
    allowed_programs: Mapping[str, Path] | None = None
    workspace_store: Any | None = None

    def __post_init__(self) -> None:
        if self.allowed_programs is None:
            self.allowed_programs = {"python": Path(sys.executable).resolve()}

    def create_task(
        self,
        original_request: str,
        project_root: Path,
        *,
        next_task_id: IdFactory = new_task_id,
        next_task_status_id: IdFactory = new_task_status_id,
    ) -> TaskRecord:
        """创建任务及首条 RUNNING 状态。"""

        task = TaskRecord(
            task_id=next_task_id(),
            original_request=original_request,
            project_root=str(project_root.resolve()),
        )
        self.state.create_task(
            task,
            TaskStatusRecord(
                task_status_id=next_task_status_id(),
                task_id=task.task_id,
                revision=1,
                status=TaskStatus.RUNNING,
                reason="任务创建",
            ),
        )
        return task

    def get_task(self, task_id: str) -> TaskStateView:
        return self.state.get_task_view(task_id)

    def list_recent_tasks(self, limit: int = 50) -> tuple[TaskStateView, ...]:
        """返回 SQLite 中最近创建的任务，而不是浏览器临时记录。"""

        return self.state.list_recent_tasks(limit)

    def send_message(
        self,
        task_id: str,
        content: str | None,
        attachment_upload_ids: tuple[str, ...] = (),
    ) -> TaskMessageRecord:
        current = self.state.task_statuses.get_current(task_id)
        if current.status is TaskStatus.CANCELLED:
            raise RuntimeError("已取消任务不能继续")
        message = self.state.record_task_message(
            message_id=f"message_{uuid4()}",
            task_id=task_id,
            content=content,
            attachment_upload_ids=attachment_upload_ids,
            resume_status_id=f"task_status_{uuid4()}",
        )
        return message

    def apply_queued_messages(self, task_id: str) -> None:
        views = self.state.list_message_views(task_id)
        action_count = len(self.state.actions.list_for_task(task_id))
        for item in views:
            if item.application is not None:
                continue
            if item.attachments:
                if self.workspace_store is None:
                    raise RuntimeError("附件消息缺少 Workspace Store")
                task = self.state.tasks.get(task_id)
                from forgemind.web.workspaces import StagedWorkspaceFile
                for attachment in item.attachments:
                    staged = StagedWorkspaceFile(**attachment.model_dump())
                    state = self.workspace_store.reconcile_publish(Path(task.project_root), staged)
                    if state == "staged":
                        self.workspace_store.publish(Path(task.project_root), staged)
            self.state.record_message_application(TaskMessageApplicationRecord(
                message_application_id=f"message_application_{uuid4()}",
                message_id=item.message.message_id,
                task_id=task_id,
                applied_after_action_sequence=action_count,
            ))

    def run_until_pause(
        self,
        task_id: str,
        *,
        max_steps: int = 20,
        on_step: Callable[[int, AgentLoopStepResult[object]], None]
        | None = None,
    ) -> ApplicationRunResult:
        """连续运行立即型步骤，并可逐轮报告模型与 Runtime 结果。"""

        if max_steps < 1:
            raise ValueError("max_steps 必须至少为 1")
        last_step: AgentLoopStepResult[object] | None = None
        if (
            self.state.task_statuses.get_current(task_id).status
            is TaskStatus.EXECUTING
        ):
            self._recover_interrupted_execution(task_id)
        for step_number in range(1, max_steps + 1):
            status = self.state.task_statuses.get_current(task_id).status
            if status is not TaskStatus.RUNNING:
                return ApplicationRunResult(
                    task_id, status, step_number - 1, last_step=last_step
                )
            self.apply_queued_messages(task_id)
            last_step = run_agent_loop_step(
                task_id=task_id,
                state=self.state,
                model=self.model,
                handlers=build_runtime_handlers(task_id=task_id, state=self.state),
                max_action_count=self.max_action_count,
            )
            # 回调发生在模型原文已经保留、Runtime 分派已经完成之后。
            # 调用方可以打印或记录本轮证据，但不能改写不可变结果。
            if on_step is not None:
                on_step(step_number, last_step)
            if isinstance(last_step.dispatch_result, AgentDecisionParseFailure):
                return ApplicationRunResult(
                    task_id,
                    TaskStatus.RUNNING,
                    step_number,
                    parse_failure=last_step.dispatch_result,
                    last_step=last_step,
                )
            status = self.state.task_statuses.get_current(task_id).status
            if status is not TaskStatus.RUNNING:
                return ApplicationRunResult(
                    task_id, status, step_number, last_step=last_step
                )
        return ApplicationRunResult(
            task_id,
            self.state.task_statuses.get_current(task_id).status,
            max_steps,
            last_step=last_step,
        )

    def _recover_interrupted_execution(self, task_id: str) -> None:
        """恢复 edit_file；进程型 Tool 则诚实记录结果未知。"""

        view = self.state.get_task_view(task_id)
        if not view.actions:
            raise RuntimeError("EXECUTING 任务缺少当前 Action")
        action = view.actions[-1].action
        if isinstance(action, AcceptedEditFileToolAction):
            resume_edit_execution(
                task_id=task_id,
                action_id=action.action_id,
                state=self.state,
            )
            return

        observation = FailedObservation(
            action_id=action.action_id,
            status="failed",
            error=ObservationError(
                code=ObservationErrorCode.EXECUTION_RESULT_UNKNOWN,
                message=(
                    "进程在执行期间中断，Runtime 无法确认外部命令是否完成；"
                    "为避免重复副作用，没有自动重试"
                ),
            ),
        )
        current = view.current_status
        running = TaskStatusRecord(
            task_status_id=new_task_status_id(),
            task_id=task_id,
            revision=current.revision + 1,
            status=TaskStatus.RUNNING,
            reason="中断的 Tool 执行结果未知，交给 Agent 重新评估",
        )
        self.state.record_execution_result_running(observation, running)

    def answer_question(
        self,
        *,
        task_id: str,
        question_action_id: str,
        raw_response: str,
        selected_option: str | None = None,
    ) -> object:
        return resume_from_user_answer(
            task_id=task_id,
            question_action_id=question_action_id,
            raw_response=raw_response,
            selected_option=selected_option,
            state=self.state,
        )

    def decide_permission(
        self,
        *,
        task_id: str,
        permission_request_id: str,
        approve: bool,
        raw_response: str,
    ) -> object:
        """按持久化请求类型执行批准或拒绝，绝不接收新参数快照。"""

        if not approve:
            return reject_permission_request(
                task_id=task_id,
                permission_request_id=permission_request_id,
                raw_response=raw_response,
                state=self.state,
            )
        request = self.state.permission_requests.get(permission_request_id)
        if request.tool_name == "edit_file":
            return approve_edit_file_permission(
                task_id=task_id,
                permission_request_id=permission_request_id,
                raw_response=raw_response,
                state=self.state,
            )
        if request.tool_name in {"run_tests", "run_command"}:
            return approve_process_permission(
                task_id=task_id,
                permission_request_id=permission_request_id,
                raw_response=raw_response,
                state=self.state,
                allowed_programs=self.allowed_programs or {},
            )
        raise ValueError(f"V0.1 不支持批准该 Tool：{request.tool_name}")
