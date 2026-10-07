from pathlib import Path

import pytest

from forgemind.tools.read_file import (
    MAX_READ_BYTES,
    ReadFileNotFoundError,
    ReadFileSystemError,
    ReadFileTargetIsDirectoryError,
    ReadFileTooLargeError,
    read_file_bytes,
)


def test_read_file_bytes_preserves_original_bytes(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    content = b"price = 100\r\n\xff"
    target.write_bytes(content)

    assert read_file_bytes(target) == content


def test_read_file_bytes_reports_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "missing.py"

    with pytest.raises(ReadFileNotFoundError) as captured:
        read_file_bytes(target)

    assert captured.value.path == target


def test_read_file_bytes_reports_directory_target(tmp_path: Path) -> None:
    target = tmp_path / "package"
    target.mkdir()

    with pytest.raises(ReadFileTargetIsDirectoryError) as captured:
        read_file_bytes(target)

    assert captured.value.path == target


def test_read_file_bytes_allows_content_at_exact_byte_limit(
    tmp_path: Path,
) -> None:
    target = tmp_path / "exact-limit.txt"
    content = b"x" * MAX_READ_BYTES
    target.write_bytes(content)

    assert read_file_bytes(target) == content


def test_read_file_bytes_rejects_content_over_byte_limit(
    tmp_path: Path,
) -> None:
    target = tmp_path / "too-large.txt"
    target.write_bytes(b"x" * (MAX_READ_BYTES + 1))

    with pytest.raises(ReadFileTooLargeError) as captured:
        read_file_bytes(target)

    assert captured.value.path == target
    assert captured.value.max_bytes == MAX_READ_BYTES
    assert captured.value.observed_bytes == MAX_READ_BYTES + 1


def test_read_file_bytes_maps_other_os_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "unreadable.py"

    def raise_os_error(*args: object, **kwargs: object) -> object:
        raise OSError("模拟系统读取失败")

    monkeypatch.setattr(Path, "open", raise_os_error)

    with pytest.raises(ReadFileSystemError) as captured:
        read_file_bytes(target)

    assert captured.value.path == target
    assert captured.value.error_type == "OSError"
