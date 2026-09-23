"""把 read_file 的同一字节快照连接到版本校验和分段结果。"""

from pathlib import Path

from forgemind.runtime.project_paths import (
    UnsafeProjectPathError,
    record_read_file_path_rejection,
    resolve_project_path,
)
from forgemind.runtime.versioning import (
    ReadFileVersionMismatchError,
    calculate_content_version,
    record_read_file_snapshot_failure,
    verify_read_file_snapshot_version,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    ReadFileSuccessObservation,
    TerminalObservation,
)
from forgemind.schema.read_file import ReadFileResult
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.read_file import (
    ReadFileNotFoundError,
    ReadFileSystemError,
    ReadFileTargetIsDirectoryError,
    ReadFileTooLargeError,
    ReadFileToolError,
    ReadFileStartLineOutOfRangeError,
    read_file_bytes,
    slice_verified_text_snapshot,
)


class ReadFileResultActionMismatchError(ValueError):
    """read_file 成功结果超出了对应 Action 的权威参数范围。"""

    def __init__(self, mismatched_fields: tuple[str, ...]) -> None:
        self.mismatched_fields = mismatched_fields
        super().__init__(
            "read_file 结果与 Action 不一致：" + ", ".join(mismatched_fields)
        )


class ReadFileToolFailureTargetMismatchError(ValueError):
    """Tool 失败引用的绝对目标与 Runtime 已解析目标不一致。"""


def build_read_file_result_from_snapshot(
    action: AcceptedReadFileToolAction,
    *,
    content: bytes,
) -> ReadFileResult:
    """从同一份已读取字节生成经过版本校验的 read_file 结果。"""

    arguments = action.arguments

    # 第一步：普通首次读取没有 expected_version，此时根据同一份 content
    # 计算并返回实际版本；已有 expected_version 时仍执行严格版本校验。
    if arguments.expected_version is None:
        version = calculate_content_version(content)
    else:
        version = verify_read_file_snapshot_version(
            action,
            content=content,
        )

    # 校验与解码必须使用同一份 content，不能在中间重新打开文件。
    text = content.decode("utf-8")

    # 分段范围来自 Runtime 已接受并冻结的 Action 参数。
    return slice_verified_text_snapshot(
        path=arguments.path,
        text=text,
        start_line=arguments.start_line,
        max_lines=arguments.max_lines,
        version=version,
    )


def verify_read_file_result_matches_action(
    action: AcceptedReadFileToolAction,
    result: ReadFileResult,
) -> ReadFileResult:
    """确认成功结果没有偏离 Runtime 接受的 Action 参数。"""

    # 第一步：取得权威参数并准备错误列表。
    arguments = action.arguments
    mismatched_fields: list[str] = []

    # 第二步：检查路径。
    if result.path != arguments.path:
        mismatched_fields.append("path")

    # 第三步：检查起始行。
    if result.start_line != arguments.start_line:
        mismatched_fields.append("start_line")

    # 第四步：检查实际返回行数不能超过批准上限。
    if result.returned_lines > arguments.max_lines:
        mismatched_fields.append("returned_lines")

    # 第五步：已有预期版本时检查结果是否属于该版本；普通首次读取没有
    # 可比较的旧版本，它返回的 result.version 就是新建立的事实。
    if (
        arguments.expected_version is not None
        and result.version != arguments.expected_version
    ):
        mismatched_fields.append("version")

    # 第六步：存在问题时一次报告全部不一致字段。
    if mismatched_fields:
        raise ReadFileResultActionMismatchError(tuple(mismatched_fields))

    # 第七步：全部一致时返回原结果。
    return result


def _map_read_file_tool_error(
    action: AcceptedReadFileToolAction,
    failure: ReadFileToolError,
) -> ObservationError:
    """把 read_file Tool 领域异常转换为对 Agent 安全的稳定错误。"""

    # 第一步：建立每种读取失败都需要公开的原请求路径详情。
    details: tuple[ObservationErrorDetail, ...] = (
        ObservationErrorDetail(
            key="requested_path",
            value=action.arguments.path,
        ),
    )

    # 第二步：文件不存在时选择 FILE_NOT_FOUND 和对应消息。
    if isinstance(failure,ReadFileNotFoundError):
        code = ObservationErrorCode.FILE_NOT_FOUND
        message = "目标文件不存在"

    # 第三步：目标是目录时选择 TARGET_IS_DIRECTORY 和对应消息。
    elif isinstance(failure,ReadFileTargetIsDirectoryError):
        code = ObservationErrorCode.TARGET_IS_DIRECTORY
        message ="目标路径是目录"


    # 第四步：文件过大时选择 FILE_TOO_LARGE，并追加上限及已观察字节数。
    elif isinstance(failure, ReadFileTooLargeError):
        code = ObservationErrorCode.FILE_TOO_LARGE
        message = "文件内容超过读取上限"
        details += (
            ObservationErrorDetail(
                key="max_bytes",
                value=str(failure.max_bytes),
            ),
            ObservationErrorDetail(
                key="observed_bytes",
                value=str(failure.observed_bytes),
            ),
        )

    # 第五步：其他系统错误选择 FILE_READ_FAILED，并追加安全的异常类型。
    elif isinstance(failure,ReadFileSystemError):
        code =ObservationErrorCode.FILE_READ_FAILED
        message ="操作系统未能读取文件"
        details += (
            ObservationErrorDetail(
                key="error_type",
                value=failure.error_type,
            ),
        )

    # 第六步：若收到未知 ReadFileToolError 子类，明确抛出 TypeError。
    else:
        raise TypeError(
            f"不支持的 read_file Tool 错误类型：{type(failure).__name__}"
        )

    # 第七步：使用选定的 code、message 和 details 构造 ObservationError。
    return ObservationError(
        code=code,
        message=message,
        details=details
    )



def record_read_file_tool_failure(
    action: AcceptedReadFileToolAction,
    failure: ReadFileToolError,
    *,
    resolved_path: Path,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """核对 Tool 目标后，把读取失败登记为 failed Observation。"""

    if failure.path != resolved_path:
        raise ReadFileToolFailureTargetMismatchError(
            "Tool 失败目标与 Runtime 已解析路径不一致"
        )

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=_map_read_file_tool_error(action, failure),
    )
    observations.record(failed)
    return failed


def _map_read_file_processing_error(
    action: AcceptedReadFileToolAction,
    failure: UnicodeDecodeError | ReadFileStartLineOutOfRangeError,
) -> ObservationError:
    """把读取字节后的文本处理异常转换为稳定错误。"""

    # 第一步：建立两种处理失败都需要的原请求路径详情。
    details: tuple[ObservationErrorDetail, ...] = (
        ObservationErrorDetail(
            key="requested_path",
            value=action.arguments.path,
        ),
    )

    # 第二步：UTF-8 解码失败时选择 INVALID_TEXT_ENCODING，
    # 并把实际尝试的编码名称加入详情。
    if isinstance(failure, UnicodeDecodeError):
        code = ObservationErrorCode.INVALID_TEXT_ENCODING
        message = "文件内容不是有效的 UTF-8 文本"
        details += (
            ObservationErrorDetail(
                key="encoding",
                value=failure.encoding,
            ),
        )

    # 第三步：起始行越界时选择 START_LINE_OUT_OF_RANGE，
    # 并把 Action 中经过 Runtime 接受的 start_line 加入详情。
    elif isinstance(failure, ReadFileStartLineOutOfRangeError):
        code = ObservationErrorCode.START_LINE_OUT_OF_RANGE
        message = "请求的起始行超过文件实际范围"
        details += (
            ObservationErrorDetail(
                key="start_line",
                value=str(action.arguments.start_line),
            ),
        )

    # 第四步：若收到契约外的异常类型，明确抛出 TypeError，不能猜测。
    else:
        raise TypeError(
            f"不支持的 read_file 文本处理错误类型：{type(failure).__name__}"
        )

    # 第五步：使用选定的 code、message 和 details 构造 ObservationError。
    return ObservationError(
        code=code,
        message=message,
        details=details,
    )


def record_read_file_processing_failure(
    action: AcceptedReadFileToolAction,
    failure: UnicodeDecodeError | ReadFileStartLineOutOfRangeError,
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """登记 read_file 已取得字节、但文本处理失败的事实。"""

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=_map_read_file_processing_error(action, failure),
    )
    observations.record(failed)
    return failed


def record_read_file_success(
    action: AcceptedReadFileToolAction,
    result: ReadFileResult,
    *,
    observations: InMemoryObservationRegistry,
) -> ReadFileSuccessObservation:
    """形成 read_file 成功事实，登记到 State 后再返回。"""

    verify_read_file_result_matches_action(action, result)

    # 成功结果必须引用权威 Action 的编号，不能另造关联标识。
    success = ReadFileSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=result,
    )

    # 先写入 State；登记失败时不能向 Agent 声称操作已经成功。
    observations.record(success)
    return success


def execute_read_file_action(
    action: AcceptedReadFileToolAction,
    *,
    project_root: Path,
    observations: InMemoryObservationRegistry,
) -> TerminalObservation:
    """执行一个已接受的 read_file Action，并登记唯一终态事实。"""

    # 第一步：把 Action 中的项目相对路径解析成安全绝对路径。
    # 若路径逃出项目根目录，立即登记 rejected 并返回，不能调用 Tool。
    try:
        resolved_path = resolve_project_path(
            project_root,
            action.arguments.path,
        )
    except UnsafeProjectPathError as failure:
        return record_read_file_path_rejection(
            action,
            failure,
            observations=observations,
        )
    # 第二步：使用已解析路径受限读取真实字节。
    # 若打开或读取失败，登记对应的 failed Observation 并返回。
    try:
        content = read_file_bytes(resolved_path)
    except ReadFileToolError as failure:
        return record_read_file_tool_failure(
            action,
            failure,
            resolved_path=resolved_path,
            observations=observations,
        )

    # 第三步：从同一份字节完成版本校验、UTF-8 解码和按行分段。
    # 若快照版本变化，登记 VERSION_MISMATCH 的 failed Observation。
    try:
        result = build_read_file_result_from_snapshot(
            action,
            content=content,
        )
    except ReadFileVersionMismatchError as failure:
        return record_read_file_snapshot_failure(
            action,
            failure,
            observations=observations,
        )
    except (
        UnicodeDecodeError,
        ReadFileStartLineOutOfRangeError,
    ) as failure:
        return record_read_file_processing_failure(
            action,
            failure,
            observations=observations,
        )

    # 第四步：若解码或行范围处理失败，登记对应的 failed Observation。


    # 第五步：只有前面全部成功，才登记并返回 success Observation。
    return record_read_file_success(
        action,
        result,
        observations=observations,
    )
