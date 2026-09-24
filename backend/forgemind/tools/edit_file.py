"""edit_file 在写盘前准备唯一、可验证的文本替换。"""

import difflib
from dataclasses import dataclass

from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction


@dataclass(frozen=True)
class PreparedEdit:
    """由同一份已验证文件快照计算出的待写入内容。"""

    before_bytes: bytes
    after_bytes: bytes
    before_version: str
    after_version: str
    diff: str


class EditFileVersionMismatchError(ValueError):
    """实际文件版本与 edit_file Action 批准的版本不一致。"""

    def __init__(self, expected_version: str, actual_version: str) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            "文件版本已变化："
            f"expected={expected_version}, actual={actual_version}"
        )


class EditTargetNotFoundError(ValueError):
    """old_text 在当前文件快照中没有精确匹配。"""


class EditTargetAmbiguousError(ValueError):
    """old_text 在当前文件快照中出现多次，无法确定修改位置。"""

    def __init__(self, match_count: int) -> None:
        self.match_count = match_count
        super().__init__(f"old_text 匹配了 {match_count} 处")


def prepare_edit_from_snapshot(
    action: AcceptedEditFileToolAction,
    *,
    content: bytes,
) -> PreparedEdit:
    """从一份文件字节快照生成唯一替换及其真实 diff。"""

    # 第一步：计算 content 的实际版本，并与 Action 中批准的版本比较。
    actual_version = calculate_content_version(content)

    # 第二步：版本不一致时立即停止；相同时才解码同一份 content。
    if actual_version != action.arguments.expected_version:
        raise EditFileVersionMismatchError(
            action.arguments.expected_version,
            actual_version,
        )
    text = content.decode("utf-8")

    # 第三步：统计 old_text 的精确匹配数；0 次和多次分别抛出领域错误。
    match_count = text.count(action.arguments.old_text)
    if match_count == 0:
        raise EditTargetNotFoundError
    if match_count > 1:
        raise EditTargetAmbiguousError(match_count)

    # 第四步：只替换唯一匹配，得到新文本和新的 UTF-8 字节。
    modified_text = text.replace(
        action.arguments.old_text,
        action.arguments.new_text,
        1,
    )
    after_bytes = modified_text.encode("utf-8")

    # 第五步：根据真实前后文本生成保留换行的 unified diff。
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            modified_text.splitlines(keepends=True),
            fromfile=f"{action.arguments.path}.before",
            tofile=f"{action.arguments.path}.after",
        )
    )

    # 第六步：返回包含前后字节、前后版本和 diff 的不可变准备结果。
    return PreparedEdit(
        before_bytes=content,
        after_bytes=after_bytes,
        before_version=actual_version,
        after_version=calculate_content_version(after_bytes),
        diff=diff,
    )

