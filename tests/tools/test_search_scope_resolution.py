from pathlib import Path

import pytest

from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.runtime.search_scope import (
    UnsupportedSearchScopeError,
    resolve_search_scope,
)


def test_resolve_search_scope_accepts_project_directory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "src"
    target.mkdir(parents=True)

    assert resolve_search_scope(root, "src") == target.resolve()


def test_resolve_search_scope_accepts_project_python_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")

    assert resolve_search_scope(root, "src/app.py") == target.resolve()


def test_resolve_search_scope_rejects_existing_non_python_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    target = root / "README.md"
    root.mkdir()
    target.write_text("text", encoding="utf-8")

    with pytest.raises(UnsupportedSearchScopeError) as captured:
        resolve_search_scope(root, "README.md")

    assert captured.value.requested_scope == "README.md"


def test_resolve_search_scope_rejects_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(UnsafeProjectPathError):
        resolve_search_scope(root, "../outside")


def test_resolve_search_scope_rejects_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(UnsafeProjectPathError):
        resolve_search_scope(root, str((tmp_path / "outside.py").resolve()))
