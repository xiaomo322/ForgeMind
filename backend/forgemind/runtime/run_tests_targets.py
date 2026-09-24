"""把 run_tests 的路径或 pytest node id 解析到项目根目录内。"""

from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.project_paths import resolve_project_path


class InvalidTestTargetError(ValueError):
    """测试目标缺少路径部分或 node id 后缀。"""

    def __init__(self, requested_target: str) -> None:
        self.requested_target = requested_target
        super().__init__(f"测试目标格式无效：{requested_target}")


@dataclass(frozen=True)
class ResolvedTestTarget:
    """保留 Agent 原目标及 Runtime 解析后的安全执行参数。"""

    requested_target: str
    resolved_path: Path
    node_suffix: str

    @property
    def command_argument(self) -> str:
        """生成传给 subprocess 的单个 pytest 参数。"""

        return f"{self.resolved_path}{self.node_suffix}"


def resolve_test_target(
    project_root: Path,
    requested_target: str,
) -> ResolvedTestTarget:
    """安全解析一个普通路径或带 `::` 后缀的 pytest node id。"""

    # 第一步：使用 partition("::") 只拆分第一个 node id 分隔符。
    path_text, separator, node_text = requested_target.partition("::")
    # 第二步：路径部分为空，或出现分隔符但后缀为空时，抛出格式错误。
    if not path_text or (separator and not node_text):
        raise InvalidTestTargetError(requested_target)
    # 第三步：只把路径部分交给 resolve_project_path 做项目边界检查。
    resolved_path = resolve_project_path(
        project_root,
        path_text,
    )
    # 第四步：有分隔符时恢复以 "::" 开头的完整 node_suffix。
    node_suffix = f"::{node_text}" if separator else ""
    # 第五步：返回原请求、安全绝对路径和 node_suffix。
    return ResolvedTestTarget(
        requested_target=requested_target,
        resolved_path=resolved_path,
        node_suffix=node_suffix,
    )


def resolve_run_tests_targets(
    project_root: Path,
    requested_targets: tuple[str, ...],
) -> tuple[ResolvedTestTarget, ...]:
    """按原顺序解析全部测试目标。"""

    return tuple(
        resolve_test_target(project_root, target)
        for target in requested_targets
    )
