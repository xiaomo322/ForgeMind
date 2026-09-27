"""连接 run_command 的策略解析、进程执行与终态 Observation。"""

from collections.abc import Mapping
from pathlib import Path

from forgemind.runtime.command_policy import (
    InvalidProgramPolicyError,
    ProgramNotAllowedError,
    ResolvedCommandContext,
    resolve_command_context,
)
from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
    RunCommandSuccessObservation,
    TerminalObservation,
)
from forgemind.schema.run_command import RunCommandResult
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.run_command import (
    CommandProcessStartError,
    CommandProcessTimeoutError,
    run_command_process,
)


class RunCommandResultContextMismatchError(ValueError):
    """run_command 结果偏离 Runtime 解析后的权威执行上下文。"""


def record_run_command_rejection(
    action: AcceptedRunCommandToolAction,
    failure: (
        UnsafeProjectPathError
        | ProgramNotAllowedError
        | InvalidProgramPolicyError
    ),
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """把 Tool 调用前的策略拦截登记为 rejected。"""

    if isinstance(failure, UnsafeProjectPathError):
        code = ObservationErrorCode.PATH_OUTSIDE_PROJECT
        message = "命令工作目录不在项目根目录内"
        details = (
            ObservationErrorDetail(
                key="working_directory",
                value=action.arguments.working_directory,
            ),
        )
    elif isinstance(failure, ProgramNotAllowedError):
        code = ObservationErrorCode.PROGRAM_NOT_ALLOWED
        message = "程序别名不在 Runtime 允许列表中"
        details = (
            ObservationErrorDetail(key="program", value=failure.program),
        )
    elif isinstance(failure, InvalidProgramPolicyError):
        code = ObservationErrorCode.INVALID_PROGRAM_POLICY
        message = "Runtime 程序策略没有提供绝对可执行文件路径"
        details = (
            ObservationErrorDetail(key="program", value=failure.program),
            ObservationErrorDetail(
                key="configured_executable",
                value=str(failure.executable),
            ),
        )
    else:
        raise TypeError(f"不支持的命令策略错误：{type(failure).__name__}")

    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=ObservationError(code=code, message=message, details=details),
    )
    observations.record(rejected)
    return rejected


def record_run_command_failure(
    action: AcceptedRunCommandToolAction,
    failure: CommandProcessStartError | CommandProcessTimeoutError,
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """把进程启动失败或超时登记为 failed。"""

    if isinstance(failure, CommandProcessStartError):
        code = ObservationErrorCode.COMMAND_START_FAILED
        message = "操作系统未能启动命令"
        details = (
            ObservationErrorDetail(
                key="error_type",
                value=failure.error_type,
            ),
        )
    elif isinstance(failure, CommandProcessTimeoutError):
        code = ObservationErrorCode.COMMAND_TIMEOUT
        message = "命令在允许时间内没有完成"
        details = (
            ObservationErrorDetail(
                key="timeout_seconds",
                value=str(failure.timeout_seconds),
            ),
            ObservationErrorDetail(
                key="duration_ms",
                value=str(failure.duration_ms),
            ),
            ObservationErrorDetail(key="stdout", value=failure.stdout),
            ObservationErrorDetail(key="stderr", value=failure.stderr),
            ObservationErrorDetail(
                key="is_output_truncated",
                value=str(failure.is_output_truncated).lower(),
            ),
        )
    else:
        raise TypeError(f"不支持的 run_command 错误：{type(failure).__name__}")

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(code=code, message=message, details=details),
    )
    observations.record(failed)
    return failed


def record_run_command_success(
    action: AcceptedRunCommandToolAction,
    context: ResolvedCommandContext,
    result: RunCommandResult,
    *,
    observations: InMemoryObservationRegistry,
) -> RunCommandSuccessObservation:
    """核对真实结果与权威上下文后，登记 success。"""

    expected_result_identity = (
        context.program,
        str(context.executable),
        context.args,
        str(context.working_directory),
    )
    actual_result_identity = (
        result.program,
        result.executable,
        result.args,
        result.working_directory,
    )
    if actual_result_identity != expected_result_identity:
        raise RunCommandResultContextMismatchError(
            "run_command 结果与 Runtime 解析上下文不一致"
        )
    if (
        context.program != action.arguments.program
        or context.args != action.arguments.args
    ):
        raise RunCommandResultContextMismatchError(
            "Runtime 解析上下文与 AcceptedAction 参数不一致"
        )

    success = RunCommandSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=result,
    )
    observations.record(success)
    return success


def execute_run_command_action(
    action: AcceptedRunCommandToolAction,
    *,
    project_root: Path,
    allowed_programs: Mapping[str, Path],
    observations: InMemoryObservationRegistry,
) -> TerminalObservation:
    """执行已接受且已获授权的 run_command Action，并登记终态。"""

    # 第一步：调用 resolve_command_context 解析程序策略和工作目录。
    try:
        context = resolve_command_context(
            project_root,
            action.arguments,
            allowed_programs=allowed_programs,
        )
    # 第二步：捕获 UnsafeProjectPathError、ProgramNotAllowedError、
    # InvalidProgramPolicyError，通过 record_run_command_rejection 返回。
    except (
        UnsafeProjectPathError,
        ProgramNotAllowedError,
        InvalidProgramPolicyError,
    ) as failure:
        return record_run_command_rejection(
            action,
            failure,
            observations=observations,
        )
    # 第三步：调用 run_command_process，timeout 来自 action.arguments。
    try:
        result = run_command_process(
            context,
            timeout_seconds=action.arguments.timeout_seconds,
        )
    # 第四步：捕获 CommandProcessStartError、CommandProcessTimeoutError，
    # 通过 record_run_command_failure 返回。
    except (
        CommandProcessStartError,
        CommandProcessTimeoutError,
    ) as failure:
        return record_run_command_failure(
            action,
            failure,
            observations=observations,
        )
    # 第五步：调用 record_run_command_success 核对并登记真实结果。
    return record_run_command_success(
        action,
        context,
        result,
        observations=observations,
    )
