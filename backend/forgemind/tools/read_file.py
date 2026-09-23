"""read_file 对已验证文本快照进行分段返回的核心逻辑。"""

from pathlib import Path

from forgemind.schema.read_file import ReadFileResult


MAX_READ_BYTES = 64 * 1024


class ReadFileToolError(Exception):
    """read_file Tool 在读取文件字节阶段的领域错误。"""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(message)


class ReadFileNotFoundError(ReadFileToolError):
    """目标文件在真正读取时不存在。"""


class ReadFileTargetIsDirectoryError(ReadFileToolError):
    """目标是目录，不能作为普通文件读取。"""


class ReadFileTooLargeError(ReadFileToolError):
    """文件内容超过 read_file 的字节硬上限。"""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int,
        observed_bytes: int,
    ) -> None:
        self.max_bytes = max_bytes
        self.observed_bytes = observed_bytes
        super().__init__(path, "文件内容超过 read_file 字节上限")


class ReadFileSystemError(ReadFileToolError):
    """文件存在性和目录类型之外的操作系统读取错误。"""

    def __init__(self, path: Path, cause: OSError) -> None:
        self.error_type = type(cause).__name__
        super().__init__(path, "操作系统未能读取文件")


class ReadFileStartLineOutOfRangeError(ValueError):
    """非空文件的请求起始行超过实际最后一行。"""


def read_file_bytes(path: Path) -> bytes:
    """从已通过 Runtime 路径检查的目标中受控读取原始字节。"""

    # 第一步：读取前若目标明确是目录，抛出目录领域错误。
    if path.is_dir():
        raise ReadFileTargetIsDirectoryError(
            path,
            "目标路径是目录，不能作为文件读取",
        )

    # 第二步：以二进制模式打开文件，最多读取字节上限再加 1 个字节。
    try:
        with path.open("rb") as file:
            content = file.read(MAX_READ_BYTES + 1)
    # 第三步：把读取时的文件不存在转换为 ReadFileNotFoundError。
    except FileNotFoundError as exc:
        raise ReadFileNotFoundError(
            path,
            "目标文件不存在",
        ) from exc

    # 第四步：若打开瞬间目标变成目录，把 IsADirectoryError 转换为目录错误。
    except IsADirectoryError as exc:
        raise ReadFileTargetIsDirectoryError(
            path,
            "目标路径是目录，不能作为文件读取",
        ) from exc

    # 第五步：把其余 OSError 转换为 ReadFileSystemError，并保留异常因果链。
    except OSError as exc:
        raise ReadFileSystemError(path, exc) from exc

    # 第六步：若实际读到上限加 1，抛出 ReadFileTooLargeError。
    if len(content) > MAX_READ_BYTES:
        raise ReadFileTooLargeError(
            path,
            max_bytes=MAX_READ_BYTES,
            observed_bytes=len(content),
        )

    # 第七步：只有完整内容未超过上限时，才返回原始 bytes。
    return content

def slice_verified_text_snapshot(
    *,
    path: str,
    text: str,
    start_line: int,
    max_lines: int,
    version: str,
) -> ReadFileResult:
    """从已完成版本校验的同一文本快照提取请求行范围。

    本函数不重新打开文件。调用方必须保证 ``text`` 与计算 ``version``
    的字节来自同一份快照。
    """

    # 拆分文本时保留原始换行符，确保返回内容与已验证快照一致。
    lines = text.splitlines(keepends=True)

    # 空文件没有实际结束行，但已经到达文件末尾。
    if not lines:
        return ReadFileResult(
            path=path,
            content="",
            end_line=None,
            start_line=start_line,
            returned_lines=0,
            eof=True,
            version=version,
            is_truncated=False,
        )

    # 非空文件的起始行必须落在实际行范围内。
    if start_line > len(lines):
        raise ReadFileStartLineOutOfRangeError

    # 把从 1 开始的协议行号转换为 Python 下标。
    start_index = start_line - 1

    # Python 切片允许结束位置超过总行数，并会自动停在文件末尾。
    end_index = start_index + max_lines
    selected_lines = lines[start_index:end_index]

    # 根据实际返回的内容报告范围，不能把请求范围误报为读取结果。
    returned_lines = len(selected_lines)
    end_line = start_line + returned_lines - 1
    content = "".join(selected_lines)

    eof = start_index + returned_lines >= len(lines)
    is_truncated = not eof

    return ReadFileResult(
        path=path,
        content=content,
        end_line=end_line,
        start_line=start_line,
        returned_lines=returned_lines,
        eof=eof,
        version=version,
        is_truncated=is_truncated,
    )
