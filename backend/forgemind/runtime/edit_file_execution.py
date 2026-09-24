"""连接 edit_file 的运行前检查、Tool 执行与终态 Observation。"""

from pathlib import Path

from forgemind.runtime.project_paths import (
    PathCheckActionMismatchError,
    UnsafeProjectPathError,
    resolve_project_path,
)
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.edit_file import EditFileResult
from forgemind.schema.observations import (
    EditFileSuccessObservation,
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
    TerminalObservation,
)
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.edit_file import (
    EditFileVersionChangedError,
    EditFileVersionMismatchError,
    EditFileWriteError,
    EditTargetAmbiguousError,
    EditTargetNotFoundError,
    PreparedEdit,
    prepare_edit_from_snapshot,
    replace_file_atomically,
)
from forgemind.tools.read_file import (
    ReadFileNotFoundError,
    ReadFileSystemError,
    ReadFileTargetIsDirectoryError,
    ReadFileTooLargeError,
    ReadFileToolError,
    read_file_bytes,
)


class EditFileToolFailureTargetMismatchError(ValueError):
    """Tool 失败引用的目标与 Runtime 已解析目标不一致。"""


def _requested_path_details(
    action: AcceptedEditFileToolAction,
) -> tuple[ObservationErrorDetail, ...]:
    return (
        ObservationErrorDetail(
            key="requested_path",
            value=action.arguments.path,
        ),
    )


def record_edit_file_path_rejection(
    action: AcceptedEditFileToolAction,
    failure: UnsafeProjectPathError,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """把项目外路径拦截登记为 rejected。"""

    if failure.requested_path != action.arguments.path:
        raise PathCheckActionMismatchError(
            "路径错误与当前 edit_file Action 的请求路径不一致"
        )
    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PATH_OUTSIDE_PROJECT,
            message="请求路径不在项目根目录内",
            details=_requested_path_details(action),
        ),
    )
    observations.record(rejected)
    return rejected


def record_edit_file_no_change_rejection(
    action: AcceptedEditFileToolAction,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """在调用 Tool 前拒绝 old_text 与 new_text 相同的 Action。"""

    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.NO_CHANGE_REQUEST,
            message="修改前后的文本相同",
            details=_requested_path_details(action),
        ),
    )
    observations.record(rejected)
    return rejected


def record_edit_file_read_failure(
    action: AcceptedEditFileToolAction,
    failure: ReadFileToolError,
    *,
    resolved_path: Path,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """把 edit_file 读取目标快照时的失败登记为 failed。"""

    if failure.path != resolved_path:
        raise EditFileToolFailureTargetMismatchError(
            "读取失败目标与 Runtime 已解析路径不一致"
        )
    details = _requested_path_details(action)
    if isinstance(failure, ReadFileNotFoundError):
        code = ObservationErrorCode.FILE_NOT_FOUND
        message = "目标文件不存在"
    elif isinstance(failure, ReadFileTargetIsDirectoryError):
        code = ObservationErrorCode.TARGET_IS_DIRECTORY
        message = "目标路径是目录"
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
    elif isinstance(failure, ReadFileSystemError):
        code = ObservationErrorCode.FILE_READ_FAILED
        message = "操作系统未能读取文件"
        details += (
            ObservationErrorDetail(
                key="error_type",
                value=failure.error_type,
            ),
        )
    else:
        raise TypeError(
            f"不支持的 edit_file 读取错误：{type(failure).__name__}"
        )
    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(code=code, message=message, details=details),
    )
    observations.record(failed)
    return failed


def record_edit_file_preparation_failure(
    action: AcceptedEditFileToolAction,
    failure: (
        EditFileVersionMismatchError
        | UnicodeDecodeError
        | EditTargetNotFoundError
        | EditTargetAmbiguousError
    ),
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """把快照校验或精确匹配失败登记为 failed。"""

    details = _requested_path_details(action)
    if isinstance(failure, EditFileVersionMismatchError):
        code = ObservationErrorCode.VERSION_MISMATCH
        message = "文件版本与用户批准的版本不一致"
        details += (
            ObservationErrorDetail(
                key="expected_version",
                value=failure.expected_version,
            ),
            ObservationErrorDetail(
                key="actual_version",
                value=failure.actual_version,
            ),
        )
    elif isinstance(failure, UnicodeDecodeError):
        code = ObservationErrorCode.INVALID_TEXT_ENCODING
        message = "文件内容不是有效的 UTF-8 文本"
        details += (
            ObservationErrorDetail(key="encoding", value=failure.encoding),
        )
    elif isinstance(failure, EditTargetNotFoundError):
        code = ObservationErrorCode.EDIT_TARGET_NOT_FOUND
        message = "当前文件中找不到要替换的精确文本"
    elif isinstance(failure, EditTargetAmbiguousError):
        code = ObservationErrorCode.EDIT_TARGET_AMBIGUOUS
        message = "要替换的精确文本在当前文件中出现多次"
        details += (
            ObservationErrorDetail(
                key="match_count",
                value=str(failure.match_count),
            ),
        )
    else:
        raise TypeError(
            f"不支持的 edit_file 准备错误：{type(failure).__name__}"
        )
    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(code=code, message=message, details=details),
    )
    observations.record(failed)
    return failed


def record_edit_file_write_failure(
    action: AcceptedEditFileToolAction,
    failure: EditFileVersionChangedError | EditFileWriteError,
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """把最终版本复查或原子写入失败登记为 failed。"""

    details = _requested_path_details(action)
    if isinstance(failure, EditFileVersionChangedError):
        code = ObservationErrorCode.VERSION_MISMATCH
        message = "写入前文件版本再次变化"
        details += (
            ObservationErrorDetail(
                key="expected_version",
                value=failure.expected_version,
            ),
            ObservationErrorDetail(
                key="actual_version",
                value=failure.actual_version,
            ),
        )
    elif isinstance(failure, EditFileWriteError):
        code = ObservationErrorCode.FILE_WRITE_FAILED
        message = "操作系统未能写入文件"
        details += (
            ObservationErrorDetail(
                key="error_type",
                value=failure.error_type,
            ),
        )
    else:
        raise TypeError(
            f"不支持的 edit_file 写入错误：{type(failure).__name__}"
        )
    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(code=code, message=message, details=details),
    )
    observations.record(failed)
    return failed


def record_edit_file_success(
    action: AcceptedEditFileToolAction,
    prepared: PreparedEdit,
    *,
    observations: InMemoryObservationRegistry,
) -> EditFileSuccessObservation:
    """根据已经写入的准备结果登记 edit_file 成功事实。"""

    result = EditFileResult(
        path=action.arguments.path,
        before_version=prepared.before_version,
        after_version=prepared.after_version,
        replacement_count=1,
        diff=prepared.diff,
    )
    success = EditFileSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=result,
    )
    observations.record(success)
    return success


def execute_edit_file_action(
    action: AcceptedEditFileToolAction,
    *,
    project_root: Path,
    observations: InMemoryObservationRegistry,
) -> TerminalObservation:
    """执行一个已获批准的 edit_file Action 并登记唯一终态。"""

    # 第一步：解析安全项目路径；路径越界时登记 rejected 并直接返回。
    try:
        resolved_path = resolve_project_path(
            project_root,
            action.arguments.path,
        )
    except UnsafeProjectPathError as failure:
        return record_edit_file_path_rejection(
            action,
            failure,
            observations=observations,
        )
    # 第二步：old_text 与 new_text 相同时，在 Tool 调用前登记 rejected。
    if action.arguments.old_text == action.arguments.new_text:
        return record_edit_file_no_change_rejection(
            action,
            observations=observations,
        )
    # 第三步：读取目标文件快照；读取领域错误登记为 failed。
    try:
        content = read_file_bytes(resolved_path)
    except ReadFileToolError as failure:
        return record_edit_file_read_failure(
            action,
            failure,
            resolved_path=resolved_path,
            observations=observations,
        )
    # 第四步：准备唯一替换；版本、编码或匹配错误登记为 failed。
    try:
        prepared = prepare_edit_from_snapshot(
            action,
            content=content,
        )
    except (
        EditFileVersionMismatchError,
        UnicodeDecodeError,
        EditTargetNotFoundError,
        EditTargetAmbiguousError,
    ) as failure:
        return record_edit_file_preparation_failure(
            action,
            failure,
            observations=observations,
        )
    # 第五步：原子写回；最终版本变化或系统写入错误登记为 failed。
    try:
        replace_file_atomically(resolved_path, prepared)
    except (
        EditFileVersionChangedError,
        EditFileWriteError,
    ) as failure:
        return record_edit_file_write_failure(
            action,
            failure,
            observations=observations,
        )
    # 第六步：只有真实写回成功，才登记并返回 success Observation。
    return record_edit_file_success(
        action,
        prepared,
        observations=observations,
    )
