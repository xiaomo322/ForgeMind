"""把 ForgeMind 内部 Agent 结果映射为公开流式事件。"""

from collections.abc import Iterator
import logging

from fastapi.encoders import jsonable_encoder

from forgemind.agent.loop import AgentLoopStepResult
from forgemind.application import ForgeMindApplication
from forgemind.runtime.ask_user import AskUserWaitingResult
from forgemind.runtime.completion import CompletionResult
from forgemind.runtime.edit_file_handler import EditFilePermissionWaitingResult
from forgemind.runtime.run_command_handler import RunCommandPermissionWaitingResult
from forgemind.runtime.run_tests_handler import RunTestsPermissionWaitingResult
from forgemind.schema.tasks import TaskStatus
from forgemind.web.events import StreamEvent


logger = logging.getLogger(__name__)

PermissionWaitingResult = (
    EditFilePermissionWaitingResult
    | RunCommandPermissionWaitingResult
    | RunTestsPermissionWaitingResult
)


def build_agent_step_event(
    *,
    task_id: str,
    sequence: int,
    step_number: int,
    step: AgentLoopStepResult[object],
) -> StreamEvent:
    """把一轮已完成的 Agent 与 Runtime 结果转换成公开事件。"""

    # decision_result 已经过严格解析；不把 raw_response 当作公开权威数据。
    decision_data = jsonable_encoder(step.turn_result.decision_result)

    # Runtime 结果可能是 dataclass，并嵌套 Pydantic 模型和 Enum；
    # jsonable_encoder 把它们递归转换为 JSON 能表达的 Python 数据。
    runtime_data = jsonable_encoder(step.dispatch_result)

    return StreamEvent(
        event="agent.step",
        sequence=sequence,
        task_id=task_id,
        data={
            "step_number": step_number,
            "decision": decision_data,
            "runtime": runtime_data,
        },
    )


def build_task_waiting_user_event(
    *,
    sequence: int,
    result: AskUserWaitingResult,
) -> StreamEvent:
    """把 Runtime 已保存的问题转换为客户端可操作的等待事件。"""

    action = result.action
    return StreamEvent(
        event="task.waiting_user",
        sequence=sequence,
        task_id=action.task_id,
        data={
            # 用户回答时必须带回原问题的 action_id，避免回答错问题。
            "question_action_id": action.action_id,
            "reason": action.reason,
            "question": action.question,
            # tuple 经 jsonable_encoder 转成 JSON 数组；自由文本问题保留 null。
            "options": jsonable_encoder(action.options),
        },
    )


def build_permission_required_event(
    *,
    sequence: int,
    result: PermissionWaitingResult,
) -> StreamEvent:
    """把已经持久化的 Tool 权限请求转换为前端确认事件。"""

    request = result.permission_request
    return StreamEvent(
        event="task.permission_required",
        sequence=sequence,
        task_id=request.task_id,
        data={
            "permission_request_id": request.permission_request_id,
            "tool_name": request.tool_name,
            "reason": request.reason,
            # 参数来自 Runtime 已冻结的权限快照。客户端批准的是这一份，
            # 后续执行也会按 request_id 重新读取同一份权威快照。
            "arguments": jsonable_encoder(request.arguments),
        },
    )


def build_task_completed_event(
    *,
    sequence: int,
    result: CompletionResult,
) -> StreamEvent:
    """用独立事件告诉客户端任务已经进入不可继续执行的完成状态。"""

    return StreamEvent(
        event="task.completed",
        sequence=sequence,
        task_id=result.action.task_id,
        data={"summary": result.action.summary},
    )


def build_task_failed_event(*, task_id: str, sequence: int) -> StreamEvent:
    """返回稳定的公开错误，详细异常只写服务端日志。"""

    return StreamEvent(
        event="task.failed",
        sequence=sequence,
        task_id=task_id,
        data={
            "category": "internal_error",
            "message": "任务执行失败，请查看服务端日志。",
        },
    )


def generate_agent_step_events(
    application: ForgeMindApplication,
    task_id: str,
    *,
    max_steps: int = 20,
    first_sequence: int = 1,
) -> Iterator[StreamEvent]:
    """每次驱动一轮 Agent，并逐条产出已经完成的步骤事件。"""

    # 参数错误必须在调用模型和 Runtime 之前暴露。
    if max_steps < 1:
        raise ValueError("max_steps 必须至少为 1")
    if first_sequence < 1:
        raise ValueError("first_sequence 必须至少为 1")

    next_sequence = first_sequence
    for step_number in range(1, max_steps + 1):
        captured_steps: list[AgentLoopStepResult[object]] = []

        # 每次只允许 Application 运行一步；回调在 Runtime 分派完成后
        # 保存这一轮的不可变结果，函数返回后即可安全地发送给客户端。
        try:
            run_result = application.run_until_pause(
                task_id,
                max_steps=1,
                on_step=lambda _, step: captured_steps.append(step),
            )
        except Exception:
            # SSE 响应可能已经发送 200 和前几条事件，因此不能再改 HTTP
            # 状态码。记录完整服务端异常，同时只发送不含路径/密钥的消息。
            logger.exception("task %s failed while producing SSE events", task_id)
            yield build_task_failed_event(
                task_id=task_id,
                sequence=next_sequence,
            )
            return

        # 非 RUNNING 任务不会执行新步骤，也就没有 agent.step 可发送。
        if not captured_steps:
            return
        if len(captured_steps) != 1:
            raise RuntimeError("单步运行产生了多于一条 Agent 结果")

        yield build_agent_step_event(
            task_id=task_id,
            sequence=next_sequence,
            step_number=step_number,
            step=captured_steps[0],
        )
        next_sequence += 1

        dispatch_result = captured_steps[0].dispatch_result
        if isinstance(dispatch_result, AskUserWaitingResult):
            # 先交出 agent.step；生成器恢复时再交出可直接展示的问题事件。
            yield build_task_waiting_user_event(
                sequence=next_sequence,
                result=dispatch_result,
            )
            return

        if isinstance(
            dispatch_result,
            (
                EditFilePermissionWaitingResult,
                RunCommandPermissionWaitingResult,
                RunTestsPermissionWaitingResult,
            ),
        ):
            yield build_permission_required_event(
                sequence=next_sequence,
                result=dispatch_result,
            )
            return

        if isinstance(dispatch_result, CompletionResult):
            yield build_task_completed_event(
                sequence=next_sequence,
                result=dispatch_result,
            )
            return

        # 解析失败需要等待下一轮修复策略；等待用户或终态也不能继续调用模型。
        if (
            run_result.parse_failure is not None
            or run_result.status is not TaskStatus.RUNNING
        ):
            return
