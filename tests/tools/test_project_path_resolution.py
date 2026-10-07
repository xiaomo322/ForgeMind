from pathlib import Path

import pytest

from forgemind.runtime.project_paths import (
    UnsafeProjectPathError,
    resolve_project_path,
)


def test_resolve_project_path_returns_normalized_path_inside_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    resolved = resolve_project_path(
        project_root,
        "src/../src/app.py",
    )

    assert resolved == (project_root / "src" / "app.py").resolve()


def test_resolve_project_path_rejects_parent_escape_to_similar_sibling(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / "project-backup").mkdir()

    with pytest.raises(UnsafeProjectPathError) as captured:
        resolve_project_path(
            project_root,
            "../project-backup/secret.txt",
        )

    assert captured.value.requested_path == "../project-backup/secret.txt"
    assert captured.value.project_root == project_root.resolve()


def test_resolve_project_path_rejects_absolute_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside_file = tmp_path / "secret.txt"

    with pytest.raises(UnsafeProjectPathError):
        resolve_project_path(project_root, str(outside_file.resolve()))


def test_escape_error_keeps_normalized_root_for_relative_root_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    relative_root = Path("project")
    relative_root.mkdir()

    with pytest.raises(UnsafeProjectPathError) as captured:
        resolve_project_path(relative_root, "../secret.txt")

    assert captured.value.project_root == relative_root.resolve()
