"""edit_file 在写盘前准备唯一、可验证的文本替换。"""

import difflib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.tools.read_file import read_file_bytes


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


class EditFileWriteError(OSError):
    """edit_file 暂存或替换文件时发生操作系统错误。"""

    def __init__(self, path: Path, cause: OSError) -> None:
        self.path = path
        self.error_type = type(cause).__name__
        super().__init__(f"操作系统未能写入文件：{path}")


class EditFileVersionChangedError(ValueError):
    """准备修改后，目标文件在最终替换前再次发生变化。"""

    def __init__(self, expected_version: str, actual_version: str) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            "写入前文件版本再次变化："
            f"expected={expected_version}, actual={actual_version}"
        )


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


def replace_file_atomically(path: Path, prepared: PreparedEdit) -> None:
    """先完整暂存新内容，再以一次原子替换更新目标文件。"""

    temporary_path: Path | None = None
    try:
        # 第一步：在写入前保存目标文件当前的权限模式。
        original_mode = stat.S_IMODE(path.stat().st_mode)
        # 第二步：在目标文件同目录创建本次专属的临时文件。
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=".forgemind-edit-",
        ) as temporary_file:
            # 第三步：写入全部 after_bytes，并执行 flush 和 os.fsync。
            temporary_path = Path(temporary_file.name)
            temporary_file.write(prepared.after_bytes)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # 第四步：把原目标文件的权限模式复制到临时文件。
        temporary_path.chmod(original_mode)

        # 第五步：重新读取目标文件；版本变化时抛出专属异常。
        current_content = read_file_bytes(path)
        current_version = calculate_content_version(current_content)
        if current_version != prepared.before_version:
            raise EditFileVersionChangedError(
                prepared.before_version,
                current_version,
            )

        # 第六步：版本仍相同时，用 os.replace 一次切换临时文件和目标文件。
        os.replace(temporary_path, path)

    except OSError as exc:
        # 第七步：把真实的操作系统异常转换为稳定的 Tool 领域错误。
        raise EditFileWriteError(path, exc) from exc
    finally:
        # 第八步：无论成功或失败，都删除仍然存在的本次临时文件。
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

