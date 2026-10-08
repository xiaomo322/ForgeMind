"""把 ForgeMind 内部 Agent 结果映射为公开流式事件。"""

from collections.abc import Iterator
import logging
from pathlib import Path

from forgemind.agent.loop import AgentLoopStepResult
from forgemind.application import ForgeMindApplication
from forgemind.runtime.ask_user import AskUserWaitingResult
from forgemind.runtime.completion import CompletionResult
from forgemind.runtime.edit_file_handler import EditFilePermissionWaitingResult
from forgemind.runtime.run_command_handler import RunCommandPermissionWaitingResult
from forgemind.runtime.run_tests_handler import RunTestsPermissionWaitingResult
from forgemind.schema.tasks import TaskStatus
from forgemind.web.events import StreamEvent
from forgemind.web.public_values import encode_public_value


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
    hidden_paths: tuple[str | Path, ...] = (),
) -> StreamEvent:
    """把一轮已完成的 Agent 与 Runtime 结果转换成公开事件。"""

    # decision_result 已经过严格解析；不把 raw_response 当作公开权威数据。
    decision_data = encode_public_value(
        step.turn_result.decision_result,
        hidden_paths=hidden_paths,
    )

    # Runtime 结果可能是 dataclass，并嵌套 Pydantic 模型和 Enum；
    # jsonable_encoder 把它们递归转换为 JSON 能表达的 Python 数据。
    runtime_data = encode_public_value(
        step.dispatch_result,
        hidden_paths=hidden_paths,
    )

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
    hidden_paths: tuple[str | Path, ...] = (),
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
            "reason": encode_public_value(action.reason, hidden_paths=hidden_paths),
            "question": encode_public_value(action.question, hidden_paths=hidden_paths),
            # tuple 经 jsonable_encoder 转成 JSON 数组；自由文本问题保留 null。
            "options": encode_public_value(action.options, hidden_paths=hidden_paths),
        },
    )


def build_permission_required_event(
    *,
    sequence: int,
    result: PermissionWaitingResult,
    hidden_paths: tuple[str | Path, ...] = (),
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
            "reason": encode_public_value(request.reason, hidden_paths=hidden_paths),
            # 参数来自 Runtime 已冻结的权限快照。客户端批准的是这一份，
            # 后续执行也会按 request_id 重新读取同一份权威快照。
            "arguments": encode_public_value(
                request.arguments,
                hidden_paths=hidden_paths,
            ),
        },
    )


def build_task_completed_event(
    *,
    sequence: int,
    result: CompletionResult,
    hidden_paths: tuple[str | Path, ...] = (),
) -> StreamEvent:
    """用独立事件告诉客户端任务已经进入不可继续执行的完成状态。"""

    return StreamEvent(
        event="task.completed",
        sequence=sequence,
        task_id=result.action.task_id,
        data={
            "summary": encode_public_value(
                result.action.summary,
                hidden_paths=hidden_paths,
            )
        },
    )


def build_task_failed_event(
    *,
    task_id: str,
    sequence: int,
    category: str = "internal_error",
    message: str = "任务执行失败，请查看服务端日志。",
) -> StreamEvent:
    """返回稳定的公开错误，详细异常只写服务端日志。"""

    return StreamEvent(
        event="task.failed",
        sequence=sequence,
        task_id=task_id,
        data={
            "category": category,
            "message": message,
        },
    )


def build_task_step_limit_event(
    *, task_id: str, sequence: int, max_steps: int
) -> StreamEvent:
    """告诉客户端本批执行已用完额度，但任务本身仍可继续。"""

    return StreamEvent(
        event="task.step_limit_reached",
        sequence=sequence,
        task_id=task_id,
        data={
            "max_steps": max_steps,
            "message": (
                f"本轮已执行 {max_steps} 步，任务仍未结束。"
                "请检查结果后再继续。"
            ),
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

        # State 内部保留完整事实；只有发送给浏览器时才隐藏服务器工作区路径。
        task_view = application.get_task(task_id)
        hidden_paths = (task_view.task.project_root,)

        yield build_agent_step_event(
            task_id=task_id,
            sequence=next_sequence,
            step_number=step_number,
            step=captured_steps[0],
            hidden_paths=hidden_paths,
        )
        next_sequence += 1

        dispatch_result = captured_steps[0].dispatch_result
        if isinstance(dispatch_result, AskUserWaitingResult):
            # 先交出 agent.step；生成器恢复时再交出可直接展示的问题事件。
            yield build_task_waiting_user_event(
                sequence=next_sequence,
                result=dispatch_result,
                hidden_paths=hidden_paths,
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
                hidden_paths=hidden_paths,
            )
            return

        if isinstance(dispatch_result, CompletionResult):
            yield build_task_completed_event(
                sequence=next_sequence,
                result=dispatch_result,
                hidden_paths=hidden_paths,
            )
            return

        # 解析失败不会产生 Action，任务仍可重试；但必须先发终止事件，
        # 否则浏览器原生 EventSource 会自动重连并无限调用模型。
        if run_result.parse_failure is not None:
            yield build_task_failed_event(
                task_id=task_id,
                sequence=next_sequence,
                category="model_output_invalid",
                message="模型输出不符合决策协议，请检查记录后重试。",
            )
            return

        # 等待用户或终态不能继续调用模型。
        if run_result.status is not TaskStatus.RUNNING:
            return

    # for 循环只有在每一步都仍为 RUNNING 时才会自然走到这里。
    # 显式事件会让浏览器关闭 EventSource，等待用户决定是否再执行一批。
    yield build_task_step_limit_event(
        task_id=task_id,
        sequence=next_sequence,
        max_steps=max_steps,
    )
