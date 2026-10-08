"""上传工作区文件存储的行为测试。"""

import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

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


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    """构造真实 ZIP 字节，让测试验证标准库解压路径。"""

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_create_from_zip_preserves_nested_project_and_exports_round_trip(
    tmp_path: Path,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    source = {
        "src/calculator.py": b"def add(a, b):\n    return a + b\n",
        "tests/test_calculator.py": b"def test_add():\n    assert 1 + 1 == 2\n",
        "README.md": "# 示例项目\n".encode(),
    }

    workspace = store.create_from_zip(_zip_bytes(source))

    root = store.resolve(workspace.workspace_id)
    assert [item.path for item in workspace.files] == sorted(source)
    assert (root / "src" / "calculator.py").read_bytes() == source["src/calculator.py"]
    with ZipFile(BytesIO(store.build_zip(root))) as exported:
        assert sorted(exported.namelist()) == sorted(source)
        assert {name: exported.read(name) for name in exported.namelist()} == source


@pytest.mark.parametrize(
    "unsafe_name",
    ["../secret.py", "/absolute.py", "C:/windows.py"],
)
def test_create_from_zip_rejects_unsafe_paths(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(InvalidWorkspaceFilenameError):
        store.create_from_zip(_zip_bytes({unsafe_name: b"pass\n"}))

    assert list((tmp_path / "workspaces").glob("workspace_*")) == []


def test_archive_entry_validation_rejects_backslash_paths() -> None:
    # ZipInfo 在 Windows 构造时会主动把反斜杠改成斜杠，因此这里在
    # 构造后赋值，模拟由其他平台或恶意工具生成的原始 ZIP 条目。
    entry = ZipInfo("safe.py")
    entry.filename = "folder\\escape.py"

    with pytest.raises(InvalidWorkspaceFilenameError):
        FileSystemWorkspaceStore._validate_archive_entries([entry])


def test_create_from_zip_rejects_symbolic_links(tmp_path: Path) -> None:
    output = BytesIO()
    link = ZipInfo("linked.py")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with ZipFile(output, "w") as archive:
        archive.writestr(link, "outside.py")

    store = FileSystemWorkspaceStore(tmp_path / "workspaces")

    with pytest.raises(InvalidWorkspaceFilenameError):
        store.create_from_zip(output.getvalue())


def test_create_from_zip_rejects_case_insensitive_duplicate_paths(
    tmp_path: Path,
) -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("src/main.py", b"pass\n")
        archive.writestr("SRC/MAIN.py", b"pass\n")

    with pytest.raises(DuplicateWorkspaceFilenameError):
        FileSystemWorkspaceStore(tmp_path / "workspaces").create_from_zip(
            output.getvalue()
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


def test_stage_file_keeps_bytes_outside_active_workspace(
    tmp_path: Path,
) -> None:
    """暂存只保存附件，不能在安全边界前改变 Tool 看到的项目。"""

    # 准备：先建立一个已经能被 Agent 使用的活动 Workspace。
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    workspace_root = store.resolve(workspace.workspace_id)
    extra_content = b"extra = 2\n"

    # 执行：把用户运行期间追加的 extra.py 保存到隔离暂存区。
    staged_files = store.stage(
        task_id="task-1",
        project_root=workspace_root,
        uploads=[WorkspaceUpload("extra.py", extra_content)],
        next_upload_id=lambda: "upload-1",
    )

    # 观察：返回的元数据来自真实字节，但活动 Workspace 尚未出现 extra.py。
    assert len(staged_files) == 1
    assert staged_files[0].upload_id == "upload-1"
    assert staged_files[0].path == "extra.py"
    assert staged_files[0].size_bytes == len(extra_content)
    assert staged_files[0].sha256 == hashlib.sha256(extra_content).hexdigest()
    assert not (workspace_root / "extra.py").exists()


def test_publish_moves_staged_file_into_active_workspace(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    workspace_root = store.resolve(workspace.workspace_id)
    staged = store.stage(
        task_id="task-1",
        project_root=workspace_root,
        uploads=[WorkspaceUpload("extra.py", b"extra = 2\n")],
        next_upload_id=lambda: "upload-1",
    )[0]

    store.publish(workspace_root, staged)

    assert (workspace_root / "extra.py").read_bytes() == b"extra = 2\n"
    assert store.reconcile_publish(workspace_root, staged) == "published"


def test_stage_rejects_existing_active_filename_without_overwrite(
    tmp_path: Path,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    workspace_root = store.resolve(workspace.workspace_id)

    with pytest.raises(DuplicateWorkspaceFilenameError):
        store.stage(
            task_id="task-1",
            project_root=workspace_root,
            uploads=[WorkspaceUpload("APP.py", b"value = 999\n")],
            next_upload_id=lambda: "upload-1",
        )

    assert (workspace_root / "app.py").read_bytes() == b"value = 1\n"


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
