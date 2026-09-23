"""在受控资源范围内执行大小写敏感的 Python 源码文本搜索。"""

import os
from pathlib import Path

from forgemind.schema.search_code import (
    SearchCodeArguments,
    SearchCodeMatch,
    SearchCodeResult,
    SearchIncompleteReason,
)


MAX_SEARCH_FILE_BYTES = 64 * 1024
IGNORED_DIRECTORY_NAMES = frozenset(
    {".git", ".venv", "__pycache__", ".test-tmp"}
)


class SearchCodeToolError(Exception):
    """search_code 在 Tool 执行阶段产生的领域错误。"""


class SearchScopeNotFoundError(SearchCodeToolError):
    """真正执行搜索时，已确认安全的 scope 不存在。"""

    def __init__(self, scope: Path) -> None:
        self.scope = scope
        super().__init__("搜索范围不存在")


def _collect_python_candidates(
    project_root: Path,
    resolved_scope: Path,
) -> tuple[Path, ...]:
    """收集并按项目相对路径排列允许搜索的 Python 文件。"""

    resolved_root = project_root.resolve()
    if resolved_scope.is_file():
        raw_candidates = (resolved_scope,)
    else:
        collected_paths: list[Path] = []
        for directory, directory_names, file_names in os.walk(
            resolved_scope,
            followlinks=False,
        ):
            # 在继续向下遍历前原地移除受控目录，避免先扫描再过滤。
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in IGNORED_DIRECTORY_NAMES
            )
            collected_paths.extend(
                Path(directory) / name
                for name in file_names
                if Path(name).suffix == ".py"
            )
        raw_candidates = tuple(collected_paths)

    candidates: list[Path] = []
    for candidate in raw_candidates:
        relative_path = candidate.relative_to(resolved_root)
        if candidate.suffix != ".py":
            continue
        if any(
            part in IGNORED_DIRECTORY_NAMES
            for part in relative_path.parts[:-1]
        ):
            continue
        candidates.append(candidate)

    return tuple(
        sorted(
            candidates,
            key=lambda path: path.relative_to(resolved_root).as_posix(),
        )
    )


def _read_candidate_text(
    project_root: Path,
    candidate: Path,
) -> str | None:
    """安全读取单个候选；无法完整读取时返回 None 表示跳过。"""

    resolved_root = project_root.resolve()
    try:
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_root):
            return None
        with resolved_candidate.open("rb") as source_file:
            content = source_file.read(MAX_SEARCH_FILE_BYTES + 1)
    except OSError:
        return None

    if len(content) > MAX_SEARCH_FILE_BYTES:
        return None

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def search_python_code(
    project_root: Path,
    resolved_scope: Path,
    arguments: SearchCodeArguments,
) -> SearchCodeResult:
    """在已经过 Runtime 范围检查的 scope 中搜索普通文本。"""

    # 安全检查只证明路径位于项目内；存在性必须由真正执行的 Tool
    # 报告，避免 Runtime 在 Tool 调用前伪造 failed 状态。
    if not resolved_scope.exists():
        raise SearchScopeNotFoundError(resolved_scope)

    # 第一步：取得按项目相对路径排序的 Python 候选文件。
    resolved_root = project_root.resolve()
    candidates = _collect_python_candidates(project_root, resolved_scope)
    # 第二步：建立 matches 列表和 incomplete_reasons 集合。
    matches: list[SearchCodeMatch] = []
    incomplete_reasons: set[SearchIncompleteReason] = set()
    limit_reached = False

    # 第三步：依次读取候选；读取结果为 None 时记录 FILE_SKIPPED 后继续。
    for candidate in candidates:
        text = _read_candidate_text(project_root, candidate)

        if text is None:
            incomplete_reasons.add(SearchIncompleteReason.FILE_SKIPPED)
            continue

        relative_path = candidate.relative_to(resolved_root).as_posix()

        # 第四步：逐行枚举文本，行号从 1 开始，只处理包含 query 的行。
        for line_number, line_text in enumerate(
            text.splitlines(),
            start=1,
        ):
            if arguments.query not in line_text:
                continue

            # 第五步：发现第 max_results + 1 条命中时记录上限并停止。
            if len(matches) >= arguments.max_results:
                incomplete_reasons.add(
                    SearchIncompleteReason.RESULT_LIMIT_REACHED
                )
                limit_reached = True
                break

            # 结果尚未达到 max_results 时追加真实匹配项。
            matches.append(
                SearchCodeMatch(
                    path=relative_path,
                    line_number=line_number,
                    line_text=line_text,
                )
            )

        # 第六步：内层发现额外命中后，同时停止外层候选扫描。
        if limit_reached:
            break

    # 第七步：按照枚举定义顺序整理原因，构造并返回 SearchCodeResult。
    ordered_reasons = tuple(
        reason
        for reason in SearchIncompleteReason
        if reason in incomplete_reasons
    )

    return SearchCodeResult(
        query=arguments.query,
        searched_scope=arguments.scope,
        matches=tuple(matches),
        returned_count=len(matches),
        is_complete=not ordered_reasons,
        incomplete_reasons=ordered_reasons,
    )
