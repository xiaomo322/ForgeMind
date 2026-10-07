import pytest

from forgemind.tools.read_file import (
    ReadFileStartLineOutOfRangeError,
    slice_verified_text_snapshot,
)


def test_slice_returns_requested_middle_lines_without_claiming_eof() -> None:
    result = slice_verified_text_snapshot(
        path="src/app.py",
        text="line1\nline2\nline3\nline4\n",
        start_line=2,
        max_lines=2,
        version="sha256:v1",
    )

    assert result.content == "line2\nline3\n"
    assert result.start_line == 2
    assert result.end_line == 3
    assert result.returned_lines == 2
    assert result.eof is False
    assert result.is_truncated is True


def test_slice_reaches_eof_when_fewer_lines_remain() -> None:
    result = slice_verified_text_snapshot(
        path="src/app.py",
        text="line1\nline2\nline3\nline4",
        start_line=3,
        max_lines=10,
        version="sha256:v1",
    )

    assert result.content == "line3\nline4"
    assert result.end_line == 4
    assert result.returned_lines == 2
    assert result.eof is True
    assert result.is_truncated is False


def test_slice_empty_file_from_first_line_is_successful() -> None:
    result = slice_verified_text_snapshot(
        path="src/empty.py",
        text="",
        start_line=1,
        max_lines=20,
        version="sha256:empty",
    )

    assert result.content == ""
    assert result.end_line is None
    assert result.returned_lines == 0
    assert result.eof is True
    assert result.is_truncated is False


def test_slice_rejects_start_line_past_nonempty_file() -> None:
    with pytest.raises(ReadFileStartLineOutOfRangeError):
        slice_verified_text_snapshot(
            path="src/app.py",
            text="line1\nline2\n",
            start_line=3,
            max_lines=20,
            version="sha256:v1",
        )
