import os
import stat
from pathlib import Path

import pytest

from forgemind.runtime.versioning import calculate_content_version
from forgemind.tools.edit_file import (
    EditFileVersionChangedError,
    EditFileWriteError,
    PreparedEdit,
    replace_file_atomically,
)


def make_prepared(before: bytes, after: bytes) -> PreparedEdit:
    return PreparedEdit(
        before_bytes=before,
        after_bytes=after,
        before_version=calculate_content_version(before),
        after_version=calculate_content_version(after),
        diff="--- app.py.before\n+++ app.py.after\n",
    )


def assert_no_temporary_edit_files(directory: Path) -> None:
    assert list(directory.glob(".forgemind-edit-*")) == []


def test_atomic_replace_writes_complete_new_content(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    before = b"discount = 1\n"
    after = b"discount = 2\n"
    target.write_bytes(before)

    replace_file_atomically(target, make_prepared(before, after))

    assert target.read_bytes() == after
    assert_no_temporary_edit_files(tmp_path)


def test_atomic_replace_preserves_target_mode(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    before = b"discount = 1\n"
    target.write_bytes(before)
    target.chmod(0o640)
    original_mode = stat.S_IMODE(target.stat().st_mode)

    replace_file_atomically(
        target,
        make_prepared(before, b"discount = 2\n"),
    )

    assert stat.S_IMODE(target.stat().st_mode) == original_mode


def test_atomic_replace_stops_when_target_changed(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    approved = b"discount = 1\n"
    changed = b"discount = 3\n"
    target.write_bytes(changed)

    with pytest.raises(EditFileVersionChangedError) as captured:
        replace_file_atomically(
            target,
            make_prepared(approved, b"discount = 2\n"),
        )

    assert captured.value.expected_version == calculate_content_version(
        approved
    )
    assert captured.value.actual_version == calculate_content_version(changed)
    assert target.read_bytes() == changed
    assert_no_temporary_edit_files(tmp_path)


def test_atomic_replace_wraps_replace_error_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "app.py"
    before = b"discount = 1\n"
    target.write_bytes(before)

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError("replace denied")

    monkeypatch.setattr("forgemind.tools.edit_file.os.replace", fail_replace)

    with pytest.raises(EditFileWriteError) as captured:
        replace_file_atomically(
            target,
            make_prepared(before, b"discount = 2\n"),
        )

    assert captured.value.path == target
    assert captured.value.error_type == "PermissionError"
    assert target.read_bytes() == before
    assert_no_temporary_edit_files(tmp_path)


def test_atomic_replace_cleans_temporary_file_when_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "app.py"
    before = b"discount = 1\n"
    target.write_bytes(before)

    def fail_fsync(file_descriptor: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(EditFileWriteError) as captured:
        replace_file_atomically(
            target,
            make_prepared(before, b"discount = 2\n"),
        )

    assert captured.value.error_type == "OSError"
    assert target.read_bytes() == before
    assert_no_temporary_edit_files(tmp_path)
