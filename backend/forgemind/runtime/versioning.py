"""Tool 执行前的文件版本门禁。"""

from hashlib import sha256

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
)
from forgemind.state.observation_registry import InMemoryObservationRegistry


class ReadFileExpectedVersionRequiredError(ValueError):
    """需要批准的读取 Action 没有绑定预期文件版本。"""


class ReadFileVersionMismatchError(ValueError):
    """实际文件版本与 Action 中批准的版本不一致。"""

    def __init__(
        self,
        *,
        action_id: str,
        expected_version: str,
        actual_version: str,
    ) -> None:
        self.action_id = action_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            "文件版本已变化："
            f"expected={expected_version}, actual={actual_version}"
        )


class VersionCheckActionMismatchError(ValueError):
    """版本错误引用的 Action 与当前准备记录的 Action 不一致。"""


def calculate_content_version(content: bytes) -> str:
    """根据完整原始字节生成稳定的 SHA-256 内容版本。"""

    # 必须基于原始字节而不是解码后的文本；换行、编码或非法字节都
    # 属于文件实际内容，隐式规范化会让不同文件得到同一个版本判断。
    return f"sha256:{sha256(content).hexdigest()}"


def verify_approved_read_file_version(
    action: AcceptedReadFileToolAction,
    *,
    actual_version: str,
) -> AcceptedReadFileToolAction:
    """确认当前文件仍是用户批准的版本，并返回同一权威 Action。"""

    expected_version = action.arguments.expected_version
    if expected_version is None:
        # 普通读取可不带版本，但经过用户权限批准的执行入口不能把
        # “未绑定版本”解释成“任意未来版本都已获授权”。
        raise ReadFileExpectedVersionRequiredError(action.action_id)

    if actual_version != expected_version:
        # 不修改 Action，也不自动接受新版本。调用方应重新读取必要
        # 上下文并根据新版本创建 Action/权限确认。
        raise ReadFileVersionMismatchError(
            action_id=action.action_id,
            expected_version=expected_version,
            actual_version=actual_version,
        )

    # 返回原对象，确保后续步骤继续使用用户批准的参数快照。
    return action


def verify_read_file_snapshot_version(
    action: AcceptedReadFileToolAction,
    *,
    content: bytes,
) -> str:
    """在 Tool 使用点验证将要返回的同一份文件字节快照。"""

    actual_version = calculate_content_version(content)
    verify_approved_read_file_version(
        action,
        actual_version=actual_version,
    )

    # Tool 后续必须从传入的同一 content 解码、分行和截取，不能验证
    # 后重新打开文件，否则检查与使用之间会再次出现竞争窗口。
    return actual_version


def _version_mismatch_error(
    mismatch: ReadFileVersionMismatchError,
) -> ObservationError:
    """把版本比较异常转换为两个终态共用的结构化错误。"""

    return ObservationError(
        code=ObservationErrorCode.VERSION_MISMATCH,
        message="文件版本与用户批准的版本不一致",
        details=(
            ObservationErrorDetail(
                key="expected_version",
                value=mismatch.expected_version,
            ),
            ObservationErrorDetail(
                key="actual_version",
                value=mismatch.actual_version,
            ),
        ),
    )


def record_read_file_version_rejection(
    action: AcceptedReadFileToolAction,
    mismatch: ReadFileVersionMismatchError,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """记录 Runtime 在 Tool 调用前发现的文件版本冲突。"""

    if mismatch.action_id != action.action_id:
        # 不能把另一 Action 的版本比较结果附到当前 Action 上。
        raise VersionCheckActionMismatchError(
            "版本错误与当前 Action 的 action_id 不一致"
        )

    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=_version_mismatch_error(mismatch),
    )

    # 版本冲突已经阻止 Tool 调用，必须先成为 State 中的权威事实，
    # Agent 才能据此重新读取上下文或发起新的权限确认。
    observations.record(rejected)
    return rejected


def record_read_file_snapshot_failure(
    action: AcceptedReadFileToolAction,
    mismatch: ReadFileVersionMismatchError,
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """记录 Tool 已读取字节后发现的版本冲突失败。"""

    if mismatch.action_id != action.action_id:
        raise VersionCheckActionMismatchError(
            "版本错误与当前 Action 的 action_id 不一致"
        )

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=_version_mismatch_error(mismatch),
    )

    # Tool 已经被调用，所以这里记录 failed；写入成功前不能向 Agent
    # 声称这次失败已成为可依赖的历史事实。
    observations.record(failed)
    return failed
