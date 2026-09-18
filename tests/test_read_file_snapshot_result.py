import pytest

from forgemind.runtime.read_file_execution import (
    build_read_file_result_from_snapshot,
)
from forgemind.runtime.versioning import (
    ReadFileVersionMismatchError,
    calculate_content_version,
)
from forgemind.schema.actions import AcceptedReadFileToolAction


def make_action(
    *,
    expected_version: str,
    start_line: int = 2,
    max_lines: int = 1,
) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/app.py",
            "start_line": start_line,
            "max_lines": max_lines,
            "expected_version": expected_version,
        },
        reason="读取已经批准的文件快照",
    )


def test_build_result_verifies_decodes_and_slices_the_same_snapshot() -> None:
    content = "标题\nprice = 100\n末尾\n".encode("utf-8")
    expected_version = calculate_content_version(content)
    action = make_action(expected_version=expected_version)

    result = build_read_file_result_from_snapshot(action, content=content)

    assert result.path == "src/app.py"
    assert result.content == "price = 100\n"
    assert result.start_line == 2
    assert result.end_line == 2
    assert result.returned_lines == 1
    assert result.eof is False
    assert result.version == expected_version
    assert result.is_truncated is True


def test_build_result_checks_version_before_decoding_changed_bytes() -> None:
    approved_content = b"price = 100\n"
    action = make_action(
        expected_version=calculate_content_version(approved_content),
        start_line=1,
    )

    # 变化后的字节同时不是合法 UTF-8；正确顺序应先报告版本变化。
    with pytest.raises(ReadFileVersionMismatchError):
        build_read_file_result_from_snapshot(action, content=b"\xff")


def test_build_result_reports_decode_error_for_approved_invalid_utf8() -> None:
    invalid_utf8 = b"\xff"
    action = make_action(
        expected_version=calculate_content_version(invalid_utf8),
        start_line=1,
    )

    # 版本相同后才进入解码，因此这里应保留真实的 UTF-8 解码错误。
    with pytest.raises(UnicodeDecodeError):
        build_read_file_result_from_snapshot(action, content=invalid_utf8)
