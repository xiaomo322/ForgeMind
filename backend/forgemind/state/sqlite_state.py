"""把同一数据库中的四个 SQLite Registry 组合成统一入口。"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Self

from forgemind.runtime.task_status import require_task_status_transition
from forgemind.runtime.user_responses import validate_user_response_for_question
from forgemind.schema.actions import (
    AcceptedAskUserAction,
    AcceptedCompletionAction,
    AcceptedToolAction,
)
from forgemind.schema.execution import EditExecutionPlan
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.observations import (
    FailedObservation,
    ObservationErrorCode,
    RejectedObservation,
    TerminalObservation,
)
from forgemind.schema.permissions import (
    PendingPermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.tasks import (
    ActionStateView,
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.schema.messages import (
    StagedAttachmentRecord,
    TaskMessageApplicationRecord,
    TaskMessageRecord,
    TaskMessageStateView,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.action_registry import DuplicateActionIdError
from forgemind.state.sqlite_connection import open_sqlite_connection
from forgemind.state.sqlite_edit_execution_plan_registry import (
    DuplicateEditExecutionPlanError,
    SQLiteEditExecutionPlanRegistry,
)
from forgemind.state.sqlite_observation_registry import (
    SQLiteObservationRegistry,
)
from forgemind.state.sqlite_permission_decision_registry import (
    SQLitePermissionDecisionRegistry,
)
from forgemind.state.sqlite_permission_request_registry import (
    SQLitePermissionRequestRegistry,
)
from forgemind.state.permission_request_registry import (
    DuplicateActionPermissionRequestError,
    DuplicatePermissionRequestIdError,
    PermissionRequestActionSnapshotMismatchError,
)
from forgemind.state.permission_decision_registry import (
    DuplicatePermissionDecisionIdError,
    DuplicatePermissionRequestDecisionError,
    PermissionDecisionRequestMismatchError,
    UnknownPermissionRequestIdError,
)
from forgemind.state.observation_registry import DuplicateObservationError
from forgemind.state.sqlite_task_registry import (
    DuplicateTaskIdError,
    SQLiteTaskRegistry,
)
from forgemind.state.sqlite_task_status_registry import (
    DuplicateTaskStatusIdError,
    InvalidInitialTaskStatusError,
    NonSequentialTaskStatusRevisionError,
    SQLiteTaskStatusRegistry,
)
from forgemind.state.sqlite_user_response_registry import (
    SQLiteUserResponseRegistry,
)
from forgemind.state.user_response_registry import (
    DuplicateQuestionResponseError,
    DuplicateUserResponseIdError,
    QuestionActionTypeError,
    UnknownQuestionActionIdError,
)


class TaskStatusTaskMismatchError(ValueError):
    """初始状态没有引用即将创建的同一个任务。"""

    def __init__(self, task_id: str, status_task_id: str) -> None:
        self.task_id = task_id
        self.status_task_id = status_task_id
        super().__init__(
            f"任务与初始状态不匹配：{task_id} != {status_task_id}"
        )


class AskUserWaitingTaskMismatchError(ValueError):
    """询问 Action 与等待状态没有引用同一任务。"""


class InvalidAskUserWaitingStatusError(ValueError):
    """询问 Action 只能与 WAITING_USER 状态一起登记。"""


class ToolPermissionWaitingTaskMismatchError(ValueError):
    """Tool Action、权限请求和等待状态没有引用同一任务。"""


class InvalidToolPermissionWaitingStatusError(ValueError):
    """待确认 Tool Action 只能与 WAITING_USER 状态一起登记。"""


class PermissionRejectionTaskMismatchError(ValueError):
    """权限拒绝决定与恢复状态没有引用同一任务。"""


class InvalidPermissionRejectionDecisionError(ValueError):
    """拒绝恢复流程只接受用户的 REJECT 决定。"""


class PermissionRejectionObservationMismatchError(ValueError):
    """拒绝 Observation 与用户决定没有引用同一 Action。"""


class InvalidPermissionRejectionRunningStatusError(ValueError):
    """权限拒绝后必须恢复为 RUNNING，交给 Agent 评估下一步。"""


class PermissionRejectionRequiresWaitingStatusError(ValueError):
    """只有等待用户授权的任务才能处理权限拒绝。"""


class PermissionRejectionNotCurrentError(ValueError):
    """用户拒绝的权限请求不属于当前最新 Action。"""


class PermissionApprovalTaskMismatchError(ValueError):
    """批准决定、执行计划和执行状态没有引用同一任务。"""


class InvalidPermissionApprovalDecisionError(ValueError):
    """批准执行流程只接受用户的 APPROVE 决定。"""


class InvalidPermissionApprovalExecutingStatusError(ValueError):
    """批准执行流程必须先进入 EXECUTING 状态。"""


class PermissionApprovalRequiresWaitingStatusError(ValueError):
    """只有等待用户授权的任务才能进入批准执行阶段。"""


class PermissionApprovalNotCurrentError(ValueError):
    """用户批准的权限请求不属于当前最新 Action。"""


class PermissionApprovalFailureObservationMismatchError(ValueError):
    """批准后的执行前失败没有引用同一个 Action。"""


class InvalidPermissionApprovalRunningStatusError(ValueError):
    """批准后若执行前失败，任务必须恢复为 RUNNING。"""


class ExecutionResultTaskMismatchError(ValueError):
    """执行结果和恢复状态没有引用同一任务的 Action。"""


class InvalidExecutionResultRunningStatusError(ValueError):
    """Tool 终态记录后必须恢复 RUNNING。"""


class ExecutionResultRequiresExecutingStatusError(ValueError):
    """只有 EXECUTING 任务才能提交外部副作用的终态。"""


class ExecutionResultNotCurrentError(ValueError):
    """执行结果不属于任务的最新 Action。"""


class CompletionRequiresRunningStatusError(ValueError):
    """只有 RUNNING 任务能够提交完成事实。"""


class CompletionHasPendingActionError(ValueError):
    """最新 Action 尚无终态或回答，任务不能完成。"""


class UserAnswerStatusTaskMismatchError(ValueError):
    """用户回答与恢复状态没有引用同一任务。"""


class InvalidUserAnswerTypeError(ValueError):
    """回答恢复流程只接受 ANSWER，不处理 CANCEL。"""


class InvalidUserAnswerRunningStatusError(ValueError):
    """有效回答只能与新的 RUNNING 状态一起登记。"""


class UserAnswerRequiresWaitingStatusError(ValueError):
    """只有当前处于 WAITING_USER 的任务才能由回答恢复。"""


class UserAnswerQuestionNotCurrentError(ValueError):
    """回答引用的不是当前等待的最新询问。"""


class UserCancelStatusTaskMismatchError(ValueError):
    """用户取消与终止状态没有引用同一任务。"""


class InvalidUserCancelTypeError(ValueError):
    """取消流程只接受 CANCEL，不处理 ANSWER。"""


class InvalidUserCancelCancelledStatusError(ValueError):
    """用户取消只能与新的 CANCELLED 状态一起登记。"""


class UserCancelRequiresWaitingStatusError(ValueError):
    """询问响应式取消只能终止 WAITING_USER 任务。"""


class UserCancelQuestionNotCurrentError(ValueError):
    """取消引用的不是当前等待的最新询问。"""


@dataclass(frozen=True, slots=True)
class SQLiteForgeMindState:
    """持有一组连接到同一数据库且依赖关系正确的 Registry。"""
    database_path: Path
    tasks: SQLiteTaskRegistry
    task_statuses: SQLiteTaskStatusRegistry
    actions: SQLiteActionRegistry
    user_responses: SQLiteUserResponseRegistry
    permission_requests: SQLitePermissionRequestRegistry
    permission_decisions: SQLitePermissionDecisionRegistry
    edit_execution_plans: SQLiteEditExecutionPlanRegistry
    observations: SQLiteObservationRegistry

    def record_staged_attachment(self, attachment: StagedAttachmentRecord) -> None:
        with open_sqlite_connection(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                "INSERT INTO staged_attachments (upload_id, task_id, payload_json) VALUES (?, ?, ?)",
                (attachment.upload_id, attachment.task_id, attachment.model_dump_json()),
            )

    def get_staged_attachment(self, upload_id: str) -> StagedAttachmentRecord:
        with open_sqlite_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM staged_attachments WHERE upload_id = ?", (upload_id,)
            ).fetchone()
        if row is None:
            raise KeyError(upload_id)
        return StagedAttachmentRecord.model_validate_json(row[0])

    def list_staged_attachments(self, task_id: str) -> tuple[StagedAttachmentRecord, ...]:
        with open_sqlite_connection(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM staged_attachments WHERE task_id=? ORDER BY upload_id",
                (task_id,),
            ).fetchall()
        return tuple(StagedAttachmentRecord.model_validate_json(row[0]) for row in rows)

    def delete_unreferenced_staged_attachment(self, task_id: str, upload_id: str) -> None:
        with open_sqlite_connection(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            referenced = connection.execute(
                "SELECT 1 FROM task_message_attachments WHERE upload_id=?", (upload_id,)
            ).fetchone()
            if referenced is not None:
                raise ValueError("已被消息引用的附件不能删除")
            deleted = connection.execute(
                "DELETE FROM staged_attachments WHERE task_id=? AND upload_id=?",
                (task_id, upload_id),
            ).rowcount
            if deleted != 1:
                raise KeyError(upload_id)

    def record_task_message(
        self,
        *,
        message_id: str,
        task_id: str,
        content: str | None,
        attachment_upload_ids: tuple[str, ...],
        resume_status_id: str,
    ) -> TaskMessageRecord:
        with open_sqlite_connection(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
                raise KeyError(task_id)
            status_row = connection.execute(
                "SELECT task_status_id, task_id, revision, status, payload_json FROM task_statuses WHERE task_id=? ORDER BY revision DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if status_row is None:
                raise KeyError(task_id)
            current_status = SQLiteTaskStatusRegistry._restore(status_row[0], list(status_row[1:]))
            if current_status.status is TaskStatus.CANCELLED:
                raise RuntimeError("已取消任务不能继续")
            for upload_id in attachment_upload_ids:
                row = connection.execute(
                    "SELECT task_id FROM staged_attachments WHERE upload_id = ?", (upload_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(upload_id)
                if row[0] != task_id:
                    raise ValueError("附件不属于当前任务")
                if connection.execute(
                    "SELECT 1 FROM task_message_attachments WHERE upload_id = ?", (upload_id,)
                ).fetchone() is not None:
                    raise ValueError("附件已经被其他消息引用")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM task_messages WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            message = TaskMessageRecord(
                message_id=message_id,
                task_id=task_id,
                sequence=sequence,
                content=content,
                attachment_upload_ids=attachment_upload_ids,
            )
            connection.execute(
                "INSERT INTO task_messages (message_id, task_id, sequence, payload_json) VALUES (?, ?, ?, ?)",
                (message.message_id, task_id, sequence, message.model_dump_json()),
            )
            for upload_id in attachment_upload_ids:
                connection.execute(
                    "INSERT INTO task_message_attachments (message_id, upload_id) VALUES (?, ?)",
                    (message.message_id, upload_id),
                )
            if current_status.status in {TaskStatus.COMPLETED, TaskStatus.BLOCKED}:
                running = TaskStatusRecord(
                    task_status_id=resume_status_id,
                    task_id=task_id,
                    revision=current_status.revision + 1,
                    status=TaskStatus.RUNNING,
                    reason="用户发送后续消息，继续同一任务",
                )
                connection.execute(
                    "INSERT INTO task_statuses (task_status_id, task_id, revision, status, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (resume_status_id, task_id, running.revision, running.status.value, running.model_dump_json()),
                )
        return message

    def record_message_application(self, application: TaskMessageApplicationRecord) -> None:
        with open_sqlite_connection(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                "INSERT INTO task_message_applications (message_id, task_id, payload_json) VALUES (?, ?, ?)",
                (application.message_id, application.task_id, application.model_dump_json()),
            )

    def resume_for_followup(self, task_id: str, status_id: str) -> TaskStatusRecord | None:
        """只允许用户后续消息把已完成或阻塞任务显式恢复。"""
        with open_sqlite_connection(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT task_status_id, task_id, revision, status, payload_json FROM task_statuses WHERE task_id=? ORDER BY revision DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            current = SQLiteTaskStatusRegistry._restore(row[0], list(row[1:]))
            if current.status not in {TaskStatus.COMPLETED, TaskStatus.BLOCKED}:
                return None
            running = TaskStatusRecord(
                task_status_id=status_id,
                task_id=task_id,
                revision=current.revision + 1,
                status=TaskStatus.RUNNING,
                reason="用户发送后续消息，继续同一任务",
            )
            connection.execute(
                "INSERT INTO task_statuses (task_status_id, task_id, revision, status, payload_json) VALUES (?, ?, ?, ?, ?)",
                (status_id, task_id, running.revision, running.status.value, running.model_dump_json()),
            )
            return running

    def list_message_views(self, task_id: str) -> tuple[TaskMessageStateView, ...]:
        with open_sqlite_connection(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM task_messages WHERE task_id = ? ORDER BY sequence", (task_id,)
            ).fetchall()
            result: list[TaskMessageStateView] = []
            for (payload,) in rows:
                message = TaskMessageRecord.model_validate_json(payload)
                app_row = connection.execute(
                    "SELECT payload_json FROM task_message_applications WHERE message_id = ?",
                    (message.message_id,),
                ).fetchone()
                attachments = tuple(
                    StagedAttachmentRecord.model_validate_json(row[0])
                    for row in connection.execute(
                        "SELECT s.payload_json FROM staged_attachments s JOIN task_message_attachments m ON m.upload_id=s.upload_id WHERE m.message_id=? ORDER BY s.upload_id",
                        (message.message_id,),
                    ).fetchall()
                )
                result.append(TaskMessageStateView(
                    message=message,
                    application=(TaskMessageApplicationRecord.model_validate_json(app_row[0]) if app_row else None),
                    attachments=attachments,
                ))
        return tuple(result)

    def record_task_completion(
        self,
        action: AcceptedCompletionAction,
        completed_status: TaskStatusRecord,
    ) -> None:
        """原子追加完成 Action 并把任务转换为 COMPLETED。"""

        if action.task_id != completed_status.task_id:
            raise TaskStatusTaskMismatchError(action.task_id, completed_status.task_id)
        if completed_status.status is not TaskStatus.COMPLETED:
            raise ValueError("完成 Action 必须与 COMPLETED 状态一起登记")
        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision, status, payload_json
                    FROM task_statuses WHERE task_id = ?
                    ORDER BY revision DESC LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(action.task_id)
                latest_status_id, *stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id, stored_status
                )
                if current.status is not TaskStatus.RUNNING:
                    raise CompletionRequiresRunningStatusError
                if completed_status.revision != current.revision + 1:
                    raise NonSequentialTaskStatusRevisionError(
                        action.task_id,
                        current.revision + 1,
                        completed_status.revision,
                    )
                require_task_status_transition(current.status, TaskStatus.COMPLETED)

                latest_action = connection.execute(
                    """
                    SELECT action_id, action_type, task_sequence FROM actions
                    WHERE task_id = ? ORDER BY task_sequence DESC LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if latest_action is not None:
                    latest_action_id, latest_action_type, latest_sequence = (
                        latest_action
                    )
                    application_rows = connection.execute(
                        """
                        SELECT payload_json FROM task_message_applications
                        WHERE task_id = ?
                        """,
                        (action.task_id,),
                    ).fetchall()
                    # 后续消息建立新的对话轮次。边界之前的最近 Action
                    # 已经属于上一轮，不能被误判成本轮尚未结束的行动。
                    applied_message_boundary = max(
                        (
                            TaskMessageApplicationRecord.model_validate_json(
                                row[0]
                            ).applied_after_action_sequence
                            for row in application_rows
                        ),
                        default=0,
                    )
                    if latest_sequence > applied_message_boundary:
                        table = (
                            "user_responses"
                            if latest_action_type == "ask_user"
                            else "observations"
                        )
                        column = (
                            "question_action_id"
                            if latest_action_type == "ask_user"
                            else "action_id"
                        )
                        terminal = connection.execute(
                            f"SELECT 1 FROM {table} WHERE {column} = ?",
                            (latest_action_id,),
                        ).fetchone()
                        if terminal is None:
                            raise CompletionHasPendingActionError

                sequence = connection.execute(
                    """
                    SELECT COALESCE(MAX(task_sequence), 0) + 1
                    FROM actions WHERE task_id = ?
                    """,
                    (action.task_id,),
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id, task_id, task_sequence,
                        action_type, tool_name, payload_json
                    ) VALUES (?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        action.action_id,
                        action.task_id,
                        sequence,
                        action.action_type,
                        action.model_dump_json(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id, task_id, revision, status, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        completed_status.task_status_id,
                        completed_status.task_id,
                        completed_status.revision,
                        completed_status.status.value,
                        completed_status.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_ask_user_waiting_conflict(action, completed_status)

    def record_permission_approval_executing(
        self,
        decision: PermissionDecisionRecord,
        plan: EditExecutionPlan,
        executing_status: TaskStatusRecord,
    ) -> None:
        """原子保存批准决定、edit_file 执行计划与 EXECUTING 状态。"""

        if not (
            decision.task_id == plan.task_id == executing_status.task_id
            and decision.action_id == plan.action_id
        ):
            raise PermissionApprovalTaskMismatchError
        if decision.decision is not PermissionDecision.APPROVE:
            raise InvalidPermissionApprovalDecisionError
        if executing_status.status is not TaskStatus.EXECUTING:
            raise InvalidPermissionApprovalExecutingStatusError

        try:
            request = self.permission_requests.get(
                decision.permission_request_id
            )
        except KeyError:
            raise UnknownPermissionRequestIdError(
                decision.permission_request_id
            ) from None
        if (
            request.task_id != decision.task_id
            or request.action_id != decision.action_id
        ):
            raise PermissionDecisionRequestMismatchError(
                decision.permission_request_id
            )
        action = self.actions.get(decision.action_id)
        SQLiteEditExecutionPlanRegistry.validate_action_snapshot(plan, action)

        decision_payload_json = decision.model_dump_json()
        status_payload_json = executing_status.model_dump_json()
        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(decision.task_id)
                latest_status_id, *stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    stored_status,
                )
                if current.status is not TaskStatus.WAITING_USER:
                    raise PermissionApprovalRequiresWaitingStatusError
                expected_revision = current.revision + 1
                if executing_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        decision.task_id,
                        expected_revision,
                        executing_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    executing_status.status,
                )

                latest_action_row = connection.execute(
                    """
                    SELECT action_id
                    FROM actions
                    WHERE task_id = ?
                    ORDER BY task_sequence DESC
                    LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if (
                    latest_action_row is None
                    or latest_action_row[0] != decision.action_id
                ):
                    raise PermissionApprovalNotCurrentError

                connection.execute(
                    """
                    INSERT INTO permission_decisions (
                        permission_decision_id, permission_request_id,
                        task_id, action_id, decision, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.permission_decision_id,
                        decision.permission_request_id,
                        decision.task_id,
                        decision.action_id,
                        decision.decision.value,
                        decision_payload_json,
                    ),
                )
                SQLiteEditExecutionPlanRegistry.insert(connection, plan)
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id, task_id, revision, status, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        executing_status.task_status_id,
                        executing_status.task_id,
                        executing_status.revision,
                        executing_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_permission_approval_executing_conflict(
                decision,
                plan,
                executing_status,
            )

    def _raise_permission_approval_executing_conflict(
        self,
        decision: PermissionDecisionRecord,
        plan: EditExecutionPlan,
        executing_status: TaskStatusRecord,
    ) -> None:
        """回滚后把批准执行事务的唯一约束冲突分类。"""

        with open_sqlite_connection(self.database_path) as connection:
            decision_id_exists = connection.execute(
                "SELECT 1 FROM permission_decisions WHERE permission_decision_id = ?",
                (decision.permission_decision_id,),
            ).fetchone()
            request_decision_exists = connection.execute(
                "SELECT 1 FROM permission_decisions WHERE permission_request_id = ?",
                (decision.permission_request_id,),
            ).fetchone()
            plan_exists = connection.execute(
                "SELECT 1 FROM edit_execution_plans WHERE action_id = ?",
                (plan.action_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (executing_status.task_status_id,),
            ).fetchone()

        if decision_id_exists is not None:
            raise DuplicatePermissionDecisionIdError(
                decision.permission_decision_id
            ) from None
        if request_decision_exists is not None:
            raise DuplicatePermissionRequestDecisionError(
                decision.permission_request_id
            ) from None
        if plan_exists is not None:
            raise DuplicateEditExecutionPlanError(plan.action_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                executing_status.task_status_id
            ) from None
        raise RuntimeError("权限批准执行记录违反未知的 SQLite 完整性约束")

    def record_permission_approval_failure_running(
        self,
        decision: PermissionDecisionRecord,
        observation: FailedObservation,
        running_status: TaskStatusRecord,
    ) -> None:
        """原子保存批准决定、执行前失败事实并恢复 Agent 循环。"""

        if decision.task_id != running_status.task_id:
            raise PermissionApprovalTaskMismatchError
        if decision.decision is not PermissionDecision.APPROVE:
            raise InvalidPermissionApprovalDecisionError
        if observation.action_id != decision.action_id:
            raise PermissionApprovalFailureObservationMismatchError
        if running_status.status is not TaskStatus.RUNNING:
            raise InvalidPermissionApprovalRunningStatusError

        try:
            request = self.permission_requests.get(
                decision.permission_request_id
            )
        except KeyError:
            raise UnknownPermissionRequestIdError(
                decision.permission_request_id
            ) from None
        if (
            request.task_id != decision.task_id
            or request.action_id != decision.action_id
        ):
            raise PermissionDecisionRequestMismatchError(
                decision.permission_request_id
            )

        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision, status, payload_json
                    FROM task_statuses WHERE task_id = ?
                    ORDER BY revision DESC LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(decision.task_id)
                latest_status_id, *stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    stored_status,
                )
                if current.status is not TaskStatus.WAITING_USER:
                    raise PermissionApprovalRequiresWaitingStatusError
                if running_status.revision != current.revision + 1:
                    raise NonSequentialTaskStatusRevisionError(
                        decision.task_id,
                        current.revision + 1,
                        running_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    running_status.status,
                )

                latest_action = connection.execute(
                    """
                    SELECT action_id FROM actions WHERE task_id = ?
                    ORDER BY task_sequence DESC LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if latest_action is None or latest_action[0] != decision.action_id:
                    raise PermissionApprovalNotCurrentError

                connection.execute(
                    """
                    INSERT INTO permission_decisions (
                        permission_decision_id, permission_request_id,
                        task_id, action_id, decision, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.permission_decision_id,
                        decision.permission_request_id,
                        decision.task_id,
                        decision.action_id,
                        decision.decision.value,
                        decision.model_dump_json(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO observations (action_id, status, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        observation.action_id,
                        observation.status,
                        observation.model_dump_json(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id, task_id, revision, status, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        running_status.task_status_id,
                        running_status.task_id,
                        running_status.revision,
                        running_status.status.value,
                        running_status.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_permission_approval_failure_running_conflict(
                decision,
                observation,
                running_status,
            )

    def _raise_permission_approval_failure_running_conflict(
        self,
        decision: PermissionDecisionRecord,
        observation: FailedObservation,
        running_status: TaskStatusRecord,
    ) -> None:
        """回滚后分类批准后执行前失败事务的唯一约束冲突。"""

        with open_sqlite_connection(self.database_path) as connection:
            decision_id_exists = connection.execute(
                "SELECT 1 FROM permission_decisions WHERE permission_decision_id = ?",
                (decision.permission_decision_id,),
            ).fetchone()
            request_decision_exists = connection.execute(
                "SELECT 1 FROM permission_decisions WHERE permission_request_id = ?",
                (decision.permission_request_id,),
            ).fetchone()
            observation_exists = connection.execute(
                "SELECT 1 FROM observations WHERE action_id = ?",
                (observation.action_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (running_status.task_status_id,),
            ).fetchone()

        if decision_id_exists is not None:
            raise DuplicatePermissionDecisionIdError(
                decision.permission_decision_id
            ) from None
        if request_decision_exists is not None:
            raise DuplicatePermissionRequestDecisionError(
                decision.permission_request_id
            ) from None
        if observation_exists is not None:
            raise DuplicateObservationError(observation.action_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                running_status.task_status_id
            ) from None
        raise RuntimeError(
            "权限批准后失败记录违反未知的 SQLite 完整性约束"
        )

    def record_process_permission_approval_executing(
        self,
        decision: PermissionDecisionRecord,
        executing_status: TaskStatusRecord,
    ) -> None:
        """原子保存 run_tests/run_command 批准和 EXECUTING 状态。"""

        if decision.task_id != executing_status.task_id:
            raise PermissionApprovalTaskMismatchError
        if decision.decision is not PermissionDecision.APPROVE:
            raise InvalidPermissionApprovalDecisionError
        if executing_status.status is not TaskStatus.EXECUTING:
            raise InvalidPermissionApprovalExecutingStatusError
        try:
            request = self.permission_requests.get(decision.permission_request_id)
        except KeyError:
            raise UnknownPermissionRequestIdError(
                decision.permission_request_id
            ) from None
        if (
            request.task_id != decision.task_id
            or request.action_id != decision.action_id
            or request.tool_name not in {"run_tests", "run_command"}
        ):
            raise PermissionDecisionRequestMismatchError(
                decision.permission_request_id
            )

        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision, status, payload_json
                    FROM task_statuses WHERE task_id = ?
                    ORDER BY revision DESC LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(decision.task_id)
                latest_status_id, *stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id, stored_status
                )
                if current.status is not TaskStatus.WAITING_USER:
                    raise PermissionApprovalRequiresWaitingStatusError
                if executing_status.revision != current.revision + 1:
                    raise NonSequentialTaskStatusRevisionError(
                        decision.task_id,
                        current.revision + 1,
                        executing_status.revision,
                    )
                require_task_status_transition(current.status, executing_status.status)
                latest_action = connection.execute(
                    """
                    SELECT action_id FROM actions WHERE task_id = ?
                    ORDER BY task_sequence DESC LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if latest_action is None or latest_action[0] != decision.action_id:
                    raise PermissionApprovalNotCurrentError
                connection.execute(
                    """
                    INSERT INTO permission_decisions (
                        permission_decision_id, permission_request_id,
                        task_id, action_id, decision, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.permission_decision_id,
                        decision.permission_request_id,
                        decision.task_id,
                        decision.action_id,
                        decision.decision.value,
                        decision.model_dump_json(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id, task_id, revision, status, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        executing_status.task_status_id,
                        executing_status.task_id,
                        executing_status.revision,
                        executing_status.status.value,
                        executing_status.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError:
            with open_sqlite_connection(self.database_path) as connection:
                decision_id_exists = connection.execute(
                    "SELECT 1 FROM permission_decisions WHERE permission_decision_id = ?",
                    (decision.permission_decision_id,),
                ).fetchone()
                request_decision_exists = connection.execute(
                    "SELECT 1 FROM permission_decisions WHERE permission_request_id = ?",
                    (decision.permission_request_id,),
                ).fetchone()
                status_exists = connection.execute(
                    "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                    (executing_status.task_status_id,),
                ).fetchone()
            if decision_id_exists is not None:
                raise DuplicatePermissionDecisionIdError(
                    decision.permission_decision_id
                ) from None
            if request_decision_exists is not None:
                raise DuplicatePermissionRequestDecisionError(
                    decision.permission_request_id
                ) from None
            if status_exists is not None:
                raise DuplicateTaskStatusIdError(
                    executing_status.task_status_id
                ) from None
            raise RuntimeError(
                "进程型 Tool 批准执行记录违反未知的 SQLite 完整性约束"
            ) from None

    def record_execution_result_running(
        self,
        observation: TerminalObservation,
        running_status: TaskStatusRecord,
    ) -> None:
        """原子保存已执行 Tool 的唯一终态，并恢复 Agent 循环。"""

        action = self.actions.get(observation.action_id)
        if action.task_id != running_status.task_id:
            raise ExecutionResultTaskMismatchError
        if running_status.status is not TaskStatus.RUNNING:
            raise InvalidExecutionResultRunningStatusError

        observation_payload_json = observation.model_dump_json()
        status_payload_json = running_status.model_dump_json()
        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(action.task_id)
                latest_status_id, *stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    stored_status,
                )
                if current.status is not TaskStatus.EXECUTING:
                    raise ExecutionResultRequiresExecutingStatusError
                expected_revision = current.revision + 1
                if running_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        action.task_id,
                        expected_revision,
                        running_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    running_status.status,
                )
                latest_action_row = connection.execute(
                    """
                    SELECT action_id FROM actions
                    WHERE task_id = ?
                    ORDER BY task_sequence DESC LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if (
                    latest_action_row is None
                    or latest_action_row[0] != observation.action_id
                ):
                    raise ExecutionResultNotCurrentError

                connection.execute(
                    """
                    INSERT INTO observations (action_id, status, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        observation.action_id,
                        observation.status,
                        observation_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id, task_id, revision, status, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        running_status.task_status_id,
                        running_status.task_id,
                        running_status.revision,
                        running_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            with open_sqlite_connection(self.database_path) as connection:
                observation_exists = connection.execute(
                    "SELECT 1 FROM observations WHERE action_id = ?",
                    (observation.action_id,),
                ).fetchone()
                status_exists = connection.execute(
                    "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                    (running_status.task_status_id,),
                ).fetchone()
            if observation_exists is not None:
                raise DuplicateObservationError(
                    observation.action_id
                ) from None
            if status_exists is not None:
                raise DuplicateTaskStatusIdError(
                    running_status.task_status_id
                ) from None
            raise RuntimeError(
                "Tool 执行终态记录违反未知的 SQLite 完整性约束"
            ) from None

    def record_tool_permission_waiting(
        self,
        action: AcceptedToolAction,
        permission_request: PendingPermissionRequest,
        waiting_status: TaskStatusRecord,
    ) -> None:
        """原子登记 Tool Action、权限请求和 WAITING_USER 状态。"""

        # 第一步：三个对象必须属于同一个任务；否则它们不能组成一条
        # 可追溯的权限链。
        if not (
            action.task_id
            == permission_request.task_id
            == waiting_status.task_id
        ):
            raise ToolPermissionWaitingTaskMismatchError

        # 第二步：用户将要确认的请求必须是当前 Action 的完整快照。
        if (
            permission_request.action_id != action.action_id
            or permission_request.action_type != action.action_type
            or permission_request.tool_name != action.tool_name
            or permission_request.arguments != action.arguments
        ):
            raise PermissionRequestActionSnapshotMismatchError(
                action.action_id
            )

        # 第三步：创建权限请求后任务必须暂停，不能继续让 Agent 产生行动。
        if waiting_status.status is not TaskStatus.WAITING_USER:
            raise InvalidToolPermissionWaitingStatusError

        action_payload_json = action.model_dump_json()
        request_payload_json = permission_request.model_dump_json()
        status_payload_json = waiting_status.model_dump_json()

        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                # 取得写锁后，其他写事务不能在状态检查和 INSERT 之间
                # 插入新事实，避免两个 Runtime 同时接受下一步。
                connection.execute("BEGIN IMMEDIATE")

                task_row = connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?",
                    (action.task_id,),
                ).fetchone()
                if task_row is None:
                    from forgemind.state.sqlite_task_registry import (
                        UnknownTaskIdError,
                    )

                    raise UnknownTaskIdError(action.task_id)

                # 必须在写事务内重新取得最新状态，不能相信事务外读取的
                # 旧快照。
                latest_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if latest_row is None:
                    raise KeyError(action.task_id)

                latest_status_id, *latest_stored_record = latest_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    latest_stored_record,
                )
                expected_revision = current.revision + 1
                if waiting_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        action.task_id,
                        expected_revision,
                        waiting_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    waiting_status.status,
                )

                sequence_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(task_sequence), 0) + 1
                    FROM actions
                    WHERE task_id = ?
                    """,
                    (action.task_id,),
                ).fetchone()
                next_sequence = sequence_row[0]

                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id,
                        task_id,
                        task_sequence,
                        action_type,
                        tool_name,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.action_id,
                        action.task_id,
                        next_sequence,
                        action.action_type,
                        action.tool_name,
                        action_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO permission_requests (
                        permission_request_id,
                        task_id,
                        action_id,
                        tool_name,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        permission_request.permission_request_id,
                        permission_request.task_id,
                        permission_request.action_id,
                        permission_request.tool_name,
                        request_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id,
                        task_id,
                        revision,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        waiting_status.task_status_id,
                        waiting_status.task_id,
                        waiting_status.revision,
                        waiting_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_tool_permission_waiting_conflict(
                action,
                permission_request,
                waiting_status,
            )

    def _raise_tool_permission_waiting_conflict(
        self,
        action: AcceptedToolAction,
        permission_request: PendingPermissionRequest,
        waiting_status: TaskStatusRecord,
    ) -> None:
        """事务回滚后把唯一约束冲突转换为稳定领域错误。"""

        with open_sqlite_connection(self.database_path) as connection:
            action_exists = connection.execute(
                "SELECT 1 FROM actions WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
            request_id_exists = connection.execute(
                """
                SELECT 1 FROM permission_requests
                WHERE permission_request_id = ?
                """,
                (permission_request.permission_request_id,),
            ).fetchone()
            action_request_exists = connection.execute(
                """
                SELECT 1 FROM permission_requests WHERE action_id = ?
                """,
                (action.action_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (waiting_status.task_status_id,),
            ).fetchone()

        if action_exists is not None:
            raise DuplicateActionIdError(action.action_id) from None
        if request_id_exists is not None:
            raise DuplicatePermissionRequestIdError(
                permission_request.permission_request_id
            ) from None
        if action_request_exists is not None:
            raise DuplicateActionPermissionRequestError(
                action.action_id
            ) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                waiting_status.task_status_id
            ) from None
        raise RuntimeError("Tool 权限等待记录违反未知的 SQLite 完整性约束")

    def record_ask_user_waiting(
        self,
        action: AcceptedAskUserAction,
        waiting_status: TaskStatusRecord,
    ) -> None:
        """原子登记询问 Action 和对应的 WAITING_USER 状态。"""

        if action.task_id != waiting_status.task_id:
            raise AskUserWaitingTaskMismatchError
        if waiting_status.status is not TaskStatus.WAITING_USER:
            raise InvalidAskUserWaitingStatusError

        action_payload_json = action.model_dump_json()
        status_payload_json = waiting_status.model_dump_json()

        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                task_row = connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?",
                    (action.task_id,),
                ).fetchone()
                if task_row is None:
                    from forgemind.state.sqlite_task_registry import (
                        UnknownTaskIdError,
                    )

                    raise UnknownTaskIdError(action.task_id)

                latest_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (action.task_id,),
                ).fetchone()
                if latest_row is None:
                    raise KeyError(action.task_id)

                latest_status_id, *latest_stored_record = latest_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    latest_stored_record,
                )
                expected_revision = current.revision + 1
                if waiting_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        action.task_id,
                        expected_revision,
                        waiting_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    waiting_status.status,
                )

                sequence_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(task_sequence), 0) + 1
                    FROM actions
                    WHERE task_id = ?
                    """,
                    (action.task_id,),
                ).fetchone()
                next_sequence = sequence_row[0]

                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id,
                        task_id,
                        task_sequence,
                        action_type,
                        tool_name,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.action_id,
                        action.task_id,
                        next_sequence,
                        action.action_type,
                        None,
                        action_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id,
                        task_id,
                        revision,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        waiting_status.task_status_id,
                        waiting_status.task_id,
                        waiting_status.revision,
                        waiting_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_ask_user_waiting_conflict(action, waiting_status)

    def _raise_ask_user_waiting_conflict(
        self,
        action: AcceptedAskUserAction,
        waiting_status: TaskStatusRecord,
    ) -> None:
        """事务回滚后把唯一约束冲突转换为稳定领域错误。"""

        with open_sqlite_connection(self.database_path) as connection:
            action_exists = connection.execute(
                "SELECT 1 FROM actions WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (waiting_status.task_status_id,),
            ).fetchone()

        if action_exists is not None:
            raise DuplicateActionIdError(action.action_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                waiting_status.task_status_id
            ) from None
        raise RuntimeError("询问等待记录违反未知的 SQLite 完整性约束")

    def record_permission_rejection_running(
        self,
        decision: PermissionDecisionRecord,
        observation: RejectedObservation,
        running_status: TaskStatusRecord,
    ) -> None:
        """原子保存用户拒绝、拒绝终态并恢复 Agent 循环。"""

        if decision.task_id != running_status.task_id:
            raise PermissionRejectionTaskMismatchError
        if decision.decision is not PermissionDecision.REJECT:
            raise InvalidPermissionRejectionDecisionError
        if (
            observation.action_id != decision.action_id
            or observation.error.code
            is not ObservationErrorCode.PERMISSION_DENIED
        ):
            raise PermissionRejectionObservationMismatchError
        if running_status.status is not TaskStatus.RUNNING:
            raise InvalidPermissionRejectionRunningStatusError

        try:
            request = self.permission_requests.get(
                decision.permission_request_id
            )
        except KeyError:
            raise UnknownPermissionRequestIdError(
                decision.permission_request_id
            ) from None
        if (
            decision.task_id != request.task_id
            or decision.action_id != request.action_id
        ):
            raise PermissionDecisionRequestMismatchError(
                decision.permission_request_id
            )

        decision_payload_json = decision.model_dump_json()
        observation_payload_json = observation.model_dump_json()
        status_payload_json = running_status.model_dump_json()

        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(decision.task_id)

                latest_status_id, *latest_stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    latest_stored_status,
                )
                if current.status is not TaskStatus.WAITING_USER:
                    raise PermissionRejectionRequiresWaitingStatusError

                expected_revision = current.revision + 1
                if running_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        decision.task_id,
                        expected_revision,
                        running_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    running_status.status,
                )

                latest_action_row = connection.execute(
                    """
                    SELECT action_id
                    FROM actions
                    WHERE task_id = ?
                    ORDER BY task_sequence DESC
                    LIMIT 1
                    """,
                    (decision.task_id,),
                ).fetchone()
                if (
                    latest_action_row is None
                    or latest_action_row[0] != decision.action_id
                ):
                    raise PermissionRejectionNotCurrentError

                connection.execute(
                    """
                    INSERT INTO permission_decisions (
                        permission_decision_id,
                        permission_request_id,
                        task_id,
                        action_id,
                        decision,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.permission_decision_id,
                        decision.permission_request_id,
                        decision.task_id,
                        decision.action_id,
                        decision.decision.value,
                        decision_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO observations (
                        action_id,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        observation.action_id,
                        observation.status,
                        observation_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id,
                        task_id,
                        revision,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        running_status.task_status_id,
                        running_status.task_id,
                        running_status.revision,
                        running_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_permission_rejection_running_conflict(
                decision,
                observation,
                running_status,
            )

    def _raise_permission_rejection_running_conflict(
        self,
        decision: PermissionDecisionRecord,
        observation: RejectedObservation,
        running_status: TaskStatusRecord,
    ) -> None:
        """回滚后把权限拒绝流程中的唯一约束冲突分类。"""

        with open_sqlite_connection(self.database_path) as connection:
            decision_id_exists = connection.execute(
                """
                SELECT 1 FROM permission_decisions
                WHERE permission_decision_id = ?
                """,
                (decision.permission_decision_id,),
            ).fetchone()
            request_decision_exists = connection.execute(
                """
                SELECT 1 FROM permission_decisions
                WHERE permission_request_id = ?
                """,
                (decision.permission_request_id,),
            ).fetchone()
            observation_exists = connection.execute(
                "SELECT 1 FROM observations WHERE action_id = ?",
                (observation.action_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (running_status.task_status_id,),
            ).fetchone()

        if decision_id_exists is not None:
            raise DuplicatePermissionDecisionIdError(
                decision.permission_decision_id
            ) from None
        if request_decision_exists is not None:
            raise DuplicatePermissionRequestDecisionError(
                decision.permission_request_id
            ) from None
        if observation_exists is not None:
            raise DuplicateObservationError(observation.action_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                running_status.task_status_id
            ) from None
        raise RuntimeError("权限拒绝恢复记录违反未知的 SQLite 完整性约束")

    def record_user_answer_running(
        self,
        response: UserResponseRecord,
        running_status: TaskStatusRecord,
    ) -> None:
        """原子保存有效回答并把任务从等待恢复为运行。"""

        if response.task_id != running_status.task_id:
            raise UserAnswerStatusTaskMismatchError
        if response.response_type is not UserResponseType.ANSWER:
            raise InvalidUserAnswerTypeError
        if running_status.status is not TaskStatus.RUNNING:
            raise InvalidUserAnswerRunningStatusError

        self._record_user_response_status(
            response,
            running_status,
            requires_waiting_error=UserAnswerRequiresWaitingStatusError,
            question_not_current_error=UserAnswerQuestionNotCurrentError,
        )

    def record_user_cancel_cancelled(
        self,
        response: UserResponseRecord,
        cancelled_status: TaskStatusRecord,
    ) -> None:
        """原子保存用户取消并把等待任务转为终止。"""

        if response.task_id != cancelled_status.task_id:
            raise UserCancelStatusTaskMismatchError
        if response.response_type is not UserResponseType.CANCEL:
            raise InvalidUserCancelTypeError
        if cancelled_status.status is not TaskStatus.CANCELLED:
            raise InvalidUserCancelCancelledStatusError

        self._record_user_response_status(
            response,
            cancelled_status,
            requires_waiting_error=UserCancelRequiresWaitingStatusError,
            question_not_current_error=UserCancelQuestionNotCurrentError,
        )

    def _record_user_response_status(
        self,
        response: UserResponseRecord,
        next_status: TaskStatusRecord,
        *,
        requires_waiting_error: type[ValueError],
        question_not_current_error: type[ValueError],
    ) -> None:
        """在一个写事务中登记询问响应及其目标状态。"""

        try:
            question = self.actions.get(response.question_action_id)
        except KeyError:
            raise UnknownQuestionActionIdError(
                response.question_action_id
            ) from None
        if not isinstance(question, AcceptedAskUserAction):
            raise QuestionActionTypeError(response.question_action_id)
        validate_user_response_for_question(response, question)

        response_payload_json = response.model_dump_json()
        status_payload_json = next_status.model_dump_json()

        try:
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                latest_status_row = connection.execute(
                    """
                    SELECT task_status_id, task_id, revision,
                           status, payload_json
                    FROM task_statuses
                    WHERE task_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (response.task_id,),
                ).fetchone()
                if latest_status_row is None:
                    raise KeyError(response.task_id)

                latest_status_id, *latest_stored_status = latest_status_row
                current = SQLiteTaskStatusRegistry._restore(
                    latest_status_id,
                    latest_stored_status,
                )
                if current.status is not TaskStatus.WAITING_USER:
                    raise requires_waiting_error()

                expected_revision = current.revision + 1
                if next_status.revision != expected_revision:
                    raise NonSequentialTaskStatusRevisionError(
                        response.task_id,
                        expected_revision,
                        next_status.revision,
                    )
                require_task_status_transition(
                    current.status,
                    next_status.status,
                )

                latest_action_row = connection.execute(
                    """
                    SELECT action_id
                    FROM actions
                    WHERE task_id = ?
                    ORDER BY task_sequence DESC
                    LIMIT 1
                    """,
                    (response.task_id,),
                ).fetchone()
                if (
                    latest_action_row is None
                    or latest_action_row[0] != response.question_action_id
                ):
                    raise question_not_current_error()

                connection.execute(
                    """
                    INSERT INTO user_responses (
                        response_id,
                        question_action_id,
                        task_id,
                        response_type,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        response.response_id,
                        response.question_action_id,
                        response.task_id,
                        response.response_type.value,
                        response_payload_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id,
                        task_id,
                        revision,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        next_status.task_status_id,
                        next_status.task_id,
                        next_status.revision,
                        next_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_user_response_status_conflict(
                response,
                next_status,
            )

    def _raise_user_response_status_conflict(
        self,
        response: UserResponseRecord,
        next_status: TaskStatusRecord,
    ) -> None:
        """事务回滚后把唯一约束冲突转为稳定领域错误。"""

        with open_sqlite_connection(self.database_path) as connection:
            response_id_exists = connection.execute(
                "SELECT 1 FROM user_responses WHERE response_id = ?",
                (response.response_id,),
            ).fetchone()
            question_response_exists = connection.execute(
                "SELECT 1 FROM user_responses WHERE question_action_id = ?",
                (response.question_action_id,),
            ).fetchone()
            status_id_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (next_status.task_status_id,),
            ).fetchone()

        if response_id_exists is not None:
            raise DuplicateUserResponseIdError(response.response_id) from None
        if question_response_exists is not None:
            raise DuplicateQuestionResponseError(
                response.question_action_id
            ) from None
        if status_id_exists is not None:
            raise DuplicateTaskStatusIdError(
                next_status.task_status_id
            ) from None
        raise RuntimeError("用户询问响应违反未知的 SQLite 完整性约束")

    def get_task_view(self, task_id: str) -> TaskStateView:
        """组合不可变任务来源、当前状态和有序 Action 历史。"""

        action_records = self.actions.list_for_task(task_id)
        action_states: list[ActionStateView] = []

        for record in action_records:
            if record.action.action_type == "ask_user":
                user_response = (
                    self.user_responses.get_optional_for_question(
                        record.action.action_id
                    )
                )
            else:
                user_response = None

            # 第一步：使用 record.action.action_id 调用
            # self.permission_requests.get_optional_for_action(...)，保存为
            # permission_request。
            permission_request = (
                self.permission_requests.get_optional_for_action(
                    record.action.action_id
                )
            )
            # 第二步：如果 permission_request 为 None，
            # permission_decision 也设为 None；否则使用请求编号调用
            # self.permission_decisions.get_optional_for_request(...)。
            if permission_request is None:
                permission_decision = None
            else:
                permission_decision = (
                    self.permission_decisions.get_optional_for_request(
                        permission_request.permission_request_id
                    )
                )
            # 第三步：构造 ActionStateView，把 sequence、action、权限请求、
            # 权限决定和按 action_id 查询的 Observation 全部传入，再追加到
            # action_states。
            action_states.append(
                ActionStateView(
                    sequence=record.sequence,
                    action=record.action,
                    user_response=user_response,
                    permission_request=permission_request,
                    permission_decision=permission_decision,
                    observation=self.observations.get_optional(
                        record.action.action_id
                    ),
                )
            )

        return TaskStateView(
            task=self.tasks.get(task_id),
            current_status=self.task_statuses.get_current(task_id),
            actions=tuple(action_states),
            messages=self.list_message_views(task_id),
        )

    def list_recent_tasks(self, limit: int) -> tuple[TaskStateView, ...]:
        """恢复最近任务的完整当前视图，供 Web 历史列表投影使用。"""

        return tuple(
            self.get_task_view(task.task_id)
            for task in self.tasks.list_recent(limit)
        )

    def create_task(
        self,
        task: TaskRecord,
        initial_status: TaskStatusRecord,
    ) -> None:
        """在一个事务中同时创建任务及 revision=1 的 RUNNING 状态。"""

        if initial_status.task_id != task.task_id:
            raise TaskStatusTaskMismatchError(
                task.task_id,
                initial_status.task_id,
            )
        if (
            initial_status.revision != 1
            or initial_status.status is not TaskStatus.RUNNING
        ):
            raise InvalidInitialTaskStatusError(task.task_id)

        task_payload_json = task.model_dump_json()
        status_payload_json = initial_status.model_dump_json()

        try:
            # 第一步：用 self.database_path 打开一个连接，在 with 事务中
            # 启用 foreign_keys，并执行 BEGIN IMMEDIATE。
            with open_sqlite_connection(self.database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")

                # 第二步：用参数化 INSERT 写入 tasks 的
                # task_id、project_root、task_payload_json。
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id,
                        project_root,
                        payload_json
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.project_root,
                        task_payload_json,
                    ),
                )

                # 第三步：仍使用同一个 connection，用参数化 INSERT 写入
                # task_statuses 的五个字段。不要调用两个 Registry 的公开
                # 方法，因为它们会各自打开连接，无法组成同一个事务。
                connection.execute(
                    """
                    INSERT INTO task_statuses (
                        task_status_id,
                        task_id,
                        revision,
                        status,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        initial_status.task_status_id,
                        initial_status.task_id,
                        initial_status.revision,
                        initial_status.status.value,
                        status_payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            self._raise_task_creation_conflict(task, initial_status)

    def _raise_task_creation_conflict(
        self,
        task: TaskRecord,
        initial_status: TaskStatusRecord,
    ) -> None:
        """在事务回滚后，把 SQLite 冲突映射为稳定领域错误。"""

        with open_sqlite_connection(self.database_path) as connection:
            task_exists = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            status_exists = connection.execute(
                "SELECT 1 FROM task_statuses WHERE task_status_id = ?",
                (initial_status.task_status_id,),
            ).fetchone()

        if task_exists is not None:
            raise DuplicateTaskIdError(task.task_id) from None
        if status_exists is not None:
            raise DuplicateTaskStatusIdError(
                initial_status.task_status_id
            ) from None

        raise RuntimeError("任务创建违反未知的 SQLite 完整性约束")

    @classmethod

    def open(cls, database_path: Path) -> Self:
        """打开数据库，并按依赖顺序建立完整的 State 入口。"""

        # 第一步：调用 resolve()，把数据库路径统一成绝对路径。
        resolved_database_path = database_path.resolve()
        resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
        with open_sqlite_connection(resolved_database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS staged_attachments (
                    upload_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_messages (
                    message_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(task_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS task_message_attachments (
                    message_id TEXT NOT NULL REFERENCES task_messages(message_id),
                    upload_id TEXT NOT NULL UNIQUE REFERENCES staged_attachments(upload_id),
                    PRIMARY KEY(message_id, upload_id)
                );
                CREATE TABLE IF NOT EXISTS task_message_applications (
                    message_id TEXT PRIMARY KEY REFERENCES task_messages(message_id),
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    payload_json TEXT NOT NULL
                );
                """
            )
        # 第二步：先创建 Task Registry，再创建 Action Registry；后续会让
        # 每个 Action 的 task_id 引用已经持久化的任务。
        tasks = SQLiteTaskRegistry(resolved_database_path)
        task_statuses = SQLiteTaskStatusRegistry(resolved_database_path)
        actions = SQLiteActionRegistry(resolved_database_path)
        user_responses = SQLiteUserResponseRegistry(
            resolved_database_path,
            actions,
        )
        # 第二步：用 resolved_database_path 和 actions 创建
        # SQLiteUserResponseRegistry，保存为 user_responses。
        # 第三步：创建 PermissionRequest Registry，并传入 Action Registry。
        permission_requests = SQLitePermissionRequestRegistry(
            resolved_database_path,
            actions,
        )
        # 第四步：创建 PermissionDecision Registry，传入请求 Registry；
        # 同时创建 Observation Registry，传入 Action Registry。
        permission_decisions = SQLitePermissionDecisionRegistry(
            resolved_database_path,
            permission_requests,
        )
        edit_execution_plans = SQLiteEditExecutionPlanRegistry(
            resolved_database_path,
            actions,
        )
        observations = SQLiteObservationRegistry(
            resolved_database_path,
            actions,
        )
        # 第五步：使用 cls(...) 返回不可变的统一 State，五个字段都要填写。
        return cls(
            database_path=resolved_database_path,
            tasks=tasks,
            task_statuses=task_statuses,
            actions=actions,
            user_responses=user_responses,
            permission_requests=permission_requests,
            permission_decisions=permission_decisions,
            edit_execution_plans=edit_execution_plans,
            observations=observations,
        )
