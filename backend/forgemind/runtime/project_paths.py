"""把 Agent 提供的项目相对路径安全解析到项目根目录内。"""

from pathlib import Path

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
)
from forgemind.state.observation_registry import InMemoryObservationRegistry


class UnsafeProjectPathError(ValueError):
    """请求路径是绝对路径，或规范化后逃出了项目根目录。"""

    def __init__(
        self,
        *,
        requested_path: str,
        project_root: Path,
        resolved_path: Path,
    ) -> None:
        self.requested_path = requested_path
        self.project_root = project_root
        self.resolved_path = resolved_path
        super().__init__(f"路径不在项目根目录内：{requested_path}")


class PathCheckActionMismatchError(ValueError):
    """路径检查结果与当前准备记录的 Action 请求路径不一致。"""


def resolve_project_path(project_root: Path, requested_path: str) -> Path:
    """解析项目相对路径，并拒绝任何项目根目录外的目标。"""

    # 第一步：把项目根目录规范化为绝对路径。
    resolved_root = project_root.resolve()

    # 第二步：把请求字符串转换为 Path 对象。
    requested = Path(requested_path)

    # 第三步：若请求带有盘符、根目录或其他 anchor，按绝对路径拒绝。
    if requested.anchor:
        raise UnsafeProjectPathError(
            requested_path=requested_path,
            project_root=resolved_root,
            resolved_path=requested.resolve(),
        )

    # 第四步：把项目根目录与相对请求组合，再规范化 ``..`` 和符号链接。
    resolved_path = (resolved_root / requested).resolve()

    # 第五步：检查最终路径是否仍属于规范化后的项目根目录。
    if not resolved_path.is_relative_to(resolved_root):
        raise UnsafeProjectPathError(
            requested_path=requested_path,
            project_root=resolved_root,
            resolved_path=resolved_path,
        )

    # 第六步：只有通过边界检查后，才返回最终绝对路径。
    return resolved_path


def record_read_file_path_rejection(
    action: AcceptedReadFileToolAction,
    unsafe_path: UnsafeProjectPathError,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """把 Runtime 的项目外路径拦截记录为 rejected Observation。"""

    # 第一步：确认路径错误属于当前 Action 请求的同一路径。
    if unsafe_path.requested_path != action.arguments.path:
        raise PathCheckActionMismatchError(
            "路径错误与当前 Action 的请求路径不一致"
        )

    # 第二步：构造只公开原请求路径的结构化错误，不泄露宿主机绝对路径。
    error = ObservationError(
        code=ObservationErrorCode.PATH_OUTSIDE_PROJECT,
        message="请求路径不在项目根目录内",
        details=(
            ObservationErrorDetail(
                key="requested_path",
                value=unsafe_path.requested_path,
            ),
        ),
    )

    # 第三步：使用权威 action_id 构造 rejected Observation。
    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=error,
    )

    # 第四步：先把拒绝事实登记到 State。
    observations.record(rejected)

    # 第五步：登记成功后返回同一 rejected 对象。
    return rejected
