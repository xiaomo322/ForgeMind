"""把 search_code 的 scope 安全解析到项目根目录内。"""

from pathlib import Path

from forgemind.runtime.project_paths import resolve_project_path


class UnsupportedSearchScopeError(ValueError):
    """scope 指向已存在的非 Python 单文件。"""

    def __init__(self, requested_scope: str) -> None:
        self.requested_scope = requested_scope
        super().__init__(f"search_code 只支持 Python 文件：{requested_scope}")


def resolve_search_scope(project_root: Path, requested_scope: str) -> Path:
    """解析 search_code 范围，并拒绝单个非 Python 文件。"""

    # 第一步：复用项目路径解析，取得规范化且位于项目根目录内的路径。
    resolved_scope = resolve_project_path(project_root, requested_scope)

    # 第二步：若目标已经存在、是文件且后缀不是 ".py"，抛出明确错误。
    if resolved_scope.is_file() and resolved_scope.suffix != ".py":
        raise UnsupportedSearchScopeError(requested_scope)

    # 第三步：目录、Python 文件或尚不存在的安全路径原样返回。
    return resolved_scope
