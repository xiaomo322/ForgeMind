"""上传工作区文件存储的行为测试。"""

from pathlib import Path

import pytest

from forgemind.web.workspaces import (
    DuplicateWorkspaceFilenameError,
    EmptyWorkspaceUploadError,
    FileSystemWorkspaceStore,
    InvalidWorkspaceEncodingError,
    InvalidWorkspaceFilenameError,
    TooManyWorkspaceFilesError,
    UnknownWorkspaceError,
    UnsupportedWorkspaceFileTypeError,
    WorkspaceFileTooLargeError,
    WorkspaceUpload,
    WorkspaceUploadTooLargeError,
)


def test_create_workspace_writes_python_files_and_returns_public_metadata(
    tmp_path: Path,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    workspace = store.create(
        [
            WorkspaceUpload("calculator.py", b"def add(a, b):\n    return a + b\n"),
            WorkspaceUpload("test_calculator.py", b"def test_add():\n    assert 1 + 1 == 2\n"),
        ]
    )

    workspace_root = store.resolve(workspace.workspace_id)
    assert workspace.workspace_id.startswith("workspace_")
    assert workspace.file_count == 2
    assert workspace.total_size_bytes == sum(file.size_bytes for file in workspace.files)
    assert [file.path for file in workspace.files] == [
        "calculator.py",
        "test_calculator.py",
    ]
    assert (workspace_root / "calculator.py").read_text(encoding="utf-8").startswith(
        "def add"
    )


def test_workspace_can_be_resolved_after_store_restart(tmp_path: Path) -> None:
    storage_root = tmp_path / "workspaces"
    first_store = FileSystemWorkspaceStore(storage_root)
    workspace = first_store.create([WorkspaceUpload("main.py", b"print('ok')\n")])

    restarted_store = FileSystemWorkspaceStore(storage_root)

    assert restarted_store.resolve(workspace.workspace_id).is_dir()


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "../secret.py", "folder/main.py", "folder\\main.py", "C:\\main.py"],
)
def test_create_workspace_rejects_unsafe_flat_filename(
    tmp_path: Path,
    filename: str,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(InvalidWorkspaceFilenameError):
        store.create([WorkspaceUpload(filename, b"pass\n")])

    assert list((tmp_path / "workspaces").glob("workspace_*")) == []


def test_create_workspace_rejects_non_python_file(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(UnsupportedWorkspaceFileTypeError):
        store.create([WorkspaceUpload("notes.txt", b"not python")])


def test_create_workspace_rejects_invalid_utf8(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(InvalidWorkspaceEncodingError):
        store.create([WorkspaceUpload("main.py", b"\xff\xfe")])


def test_create_workspace_rejects_case_insensitive_duplicate_names(
    tmp_path: Path,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(DuplicateWorkspaceFilenameError):
        store.create(
            [WorkspaceUpload("main.py", b"pass\n"), WorkspaceUpload("MAIN.py", b"pass\n")]
        )


def test_create_workspace_rejects_empty_upload(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(EmptyWorkspaceUploadError):
        store.create([])


def test_create_workspace_rejects_more_than_twenty_files(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(TooManyWorkspaceFilesError):
        store.create(
            [WorkspaceUpload(f"module_{index}.py", b"pass\n") for index in range(21)]
        )


def test_create_workspace_rejects_file_larger_than_one_mib(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(WorkspaceFileTooLargeError):
        store.create([WorkspaceUpload("large.py", b"x" * (1024 * 1024 + 1))])


def test_create_workspace_rejects_total_larger_than_five_mib(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    one_mib = b"x" * (1024 * 1024)

    with pytest.raises(WorkspaceUploadTooLargeError):
        store.create(
            [WorkspaceUpload(f"module_{index}.py", one_mib) for index in range(6)]
        )


def test_resolve_rejects_unknown_or_malformed_workspace_id(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(UnknownWorkspaceError):
        store.resolve("workspace_missing")
    with pytest.raises(UnknownWorkspaceError):
        store.resolve("../outside")
