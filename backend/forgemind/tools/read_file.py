"""read_file 对已验证文本快照进行分段返回的核心逻辑。"""

from forgemind.schema.read_file import ReadFileResult


class ReadFileStartLineOutOfRangeError(ValueError):
    """非空文件的请求起始行超过实际最后一行。"""


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
