"""连接 run_tests 的目标检查、pytest 执行与终态 Observation。"""

from pathlib import Path

from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.runtime.run_tests_targets import (
    InvalidTestTargetError,
    resolve_run_tests_targets,
)
from forgemind.schema.actions import AcceptedRunTestsToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
    RunTestsSuccessObservation,
    TerminalObservation,
)
from forgemind.schema.run_tests import RunTestsResult
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.run_tests import (
    PytestProcessStartError,
    PytestProcessTimeoutError,
    PytestReportInvalidError,
    PytestReportTooLargeError,
    PytestReportUnavailableError,
    run_pytest,
)


class RunTestsResultActionMismatchError(ValueError):
    """run_tests 成功结果偏离 AcceptedAction 的权威参数。"""


def _target_details(
    action: AcceptedRunTestsToolAction,
) -> tuple[ObservationErrorDetail, ...]:
    return tuple(
        ObservationErrorDetail(key="requested_target", value=target)
        for target in action.arguments.targets
    )


def _process_details(
    *,
    exit_code: int | None,
    duration_ms: int,
    stdout: str,
    stderr: str,
    is_output_truncated: bool,
) -> tuple[ObservationErrorDetail, ...]:
    details = (
        ObservationErrorDetail(key="duration_ms", value=str(duration_ms)),
        ObservationErrorDetail(key="stdout", value=stdout),
        ObservationErrorDetail(key="stderr", value=stderr),
        ObservationErrorDetail(
            key="is_output_truncated",
            value=str(is_output_truncated).lower(),
        ),
    )
    if exit_code is None:
        return details
    return (
        ObservationErrorDetail(key="exit_code", value=str(exit_code)),
    ) + details


def record_run_tests_target_rejection(
    action: AcceptedRunTestsToolAction,
    failure: UnsafeProjectPathError | InvalidTestTargetError,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """把 Tool 调用前的测试目标拦截登记为 rejected。"""

    if isinstance(failure, UnsafeProjectPathError):
        failed_target = failure.requested_path
        code = ObservationErrorCode.PATH_OUTSIDE_PROJECT
        message = "测试目标不在项目根目录内"
    elif isinstance(failure, InvalidTestTargetError):
        failed_target = failure.requested_target
        code = ObservationErrorCode.INVALID_TEST_TARGET
        message = "pytest 测试目标格式无效"
    else:
        raise TypeError(f"不支持的测试目标错误：{type(failure).__name__}")

    if failed_target not in action.arguments.targets:
        raise ValueError("测试目标错误与当前 Action 参数不一致")

    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=ObservationError(
            code=code,
            message=message,
            details=(
                ObservationErrorDetail(
                    key="rejected_target",
                    value=failed_target,
                ),
            ),
        ),
    )
    observations.record(rejected)
    return rejected


def record_run_tests_failure(
    action: AcceptedRunTestsToolAction,
    failure: (
        PytestProcessStartError
        | PytestProcessTimeoutError
        | PytestReportUnavailableError
        | PytestReportTooLargeError
        | PytestReportInvalidError
    ),
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """把 pytest 启动、超时或报告失败登记为 failed。"""

    details = _target_details(action)
    if isinstance(failure, PytestProcessStartError):
        code = ObservationErrorCode.TEST_RUNNER_START_FAILED
        message = "操作系统未能启动 pytest"
        details += (
            ObservationErrorDetail(
                key="error_type",
                value=failure.error_type,
            ),
        )
    elif isinstance(failure, PytestProcessTimeoutError):
        code = ObservationErrorCode.TEST_RUNNER_TIMEOUT
        message = "pytest 在允许时间内没有完成"
        details += (
            ObservationErrorDetail(
                key="timeout_seconds",
                value=str(failure.timeout_seconds),
            ),
        ) + _process_details(
            exit_code=None,
            duration_ms=failure.duration_ms,
            stdout=failure.stdout,
            stderr=failure.stderr,
            is_output_truncated=failure.is_output_truncated,
        )
    elif isinstance(failure, PytestReportUnavailableError):
        code = ObservationErrorCode.TEST_REPORT_UNAVAILABLE
        message = "pytest 没有产生 JUnit XML 报告"
        details += _process_details(
            exit_code=failure.exit_code,
            duration_ms=failure.duration_ms,
            stdout=failure.stdout,
            stderr=failure.stderr,
            is_output_truncated=failure.is_output_truncated,
        )
    elif isinstance(failure, PytestReportTooLargeError):
        code = ObservationErrorCode.TEST_REPORT_TOO_LARGE
        message = "pytest JUnit XML 报告超过字节上限"
        details += (
            ObservationErrorDetail(
                key="max_bytes",
                value=str(failure.max_bytes),
            ),
        ) + _process_details(
            exit_code=failure.exit_code,
            duration_ms=failure.duration_ms,
            stdout=failure.stdout,
            stderr=failure.stderr,
            is_output_truncated=failure.is_output_truncated,
        )
    elif isinstance(failure, PytestReportInvalidError):
        code = ObservationErrorCode.TEST_REPORT_INVALID
        message = "pytest JUnit XML 报告无法形成可信结果"
        details += (
            ObservationErrorDetail(
                key="error_type",
                value=failure.error_type,
            ),
        ) + _process_details(
            exit_code=failure.exit_code,
            duration_ms=failure.duration_ms,
            stdout=failure.stdout,
            stderr=failure.stderr,
            is_output_truncated=failure.is_output_truncated,
        )
    else:
        raise TypeError(f"不支持的 run_tests 错误：{type(failure).__name__}")

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(code=code, message=message, details=details),
    )
    observations.record(failed)
    return failed


def record_run_tests_success(
    action: AcceptedRunTestsToolAction,
    result: RunTestsResult,
    *,
    observations: InMemoryObservationRegistry,
) -> RunTestsSuccessObservation:
    """核对 pytest 结果后，登记并返回成功执行事实。"""

    if result.targets != action.arguments.targets:
        raise RunTestsResultActionMismatchError(
            "run_tests 结果目标与 AcceptedAction 参数不一致"
        )
    success = RunTestsSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=result,
    )
    observations.record(success)
    return success


def execute_run_tests_action(
    action: AcceptedRunTestsToolAction,
    *,
    project_root: Path,
    observations: InMemoryObservationRegistry,
) -> TerminalObservation:
    """执行已接受的 run_tests Action，并登记唯一终态事实。"""

    # 第一步：调用 resolve_run_tests_targets 解析 action.arguments.targets。
    try:
        resolved_targets = resolve_run_tests_targets(
            project_root,
            action.arguments.targets,
        )
    # 第二步：UnsafeProjectPathError 或 InvalidTestTargetError 表示 Tool 尚未
    # 调用，应通过 record_run_tests_target_rejection 登记 rejected 并返回。
    except (
        UnsafeProjectPathError,
        InvalidTestTargetError,
    ) as failure:
        return record_run_tests_target_rejection(
            action,
            failure,
            observations=observations,
        )
    # 第三步：使用 project_root、action.arguments 和 resolved_targets
    # 调用 run_pytest，取得可信 RunTestsResult。
    try:
        result = run_pytest(
            project_root,
            action.arguments,
            resolved_targets,
        )
    except (
        PytestProcessStartError,
        PytestProcessTimeoutError,
        PytestReportUnavailableError,
        PytestReportTooLargeError,
        PytestReportInvalidError,
    ) as failure:
        # 第四步：捕获五种 RunTests Tool 错误，通过
        # record_run_tests_failure 登记 failed 并返回。
        return record_run_tests_failure(
            action,
            failure,
            observations=observations,
        )
    # 第五步：Tool 返回结果后，通过 record_run_tests_success 登记 success。
    # 即使 result.test_outcome 是 failed，顶层仍是 success，因为 Tool
    # 已经成功取得“测试用例失败”的真实证据。
    return record_run_tests_success(
        action,
        result,
        observations=observations,
    )
