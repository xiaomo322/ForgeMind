from pathlib import Path

import pytest

from forgemind.schema.search_code import (
    SearchCodeArguments,
    SearchIncompleteReason,
)
from forgemind.tools.search_code import (
    MAX_SEARCH_FILE_BYTES,
    SearchScopeNotFoundError,
    search_python_code,
)


def write_source(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_search_returns_matches_in_deterministic_order(tmp_path: Path) -> None:
    root = tmp_path / "project"
    write_source(root / "b.py", "discount = 2\n")
    write_source(root / "a.py", "x = 1\ndiscount = 1\n")

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount"),
    )

    assert [
        (match.path, match.line_number, match.line_text)
        for match in result.matches
    ] == [
        ("a.py", 2, "discount = 1"),
        ("b.py", 1, "discount = 2"),
    ]
    assert result.returned_count == 2
    assert result.is_complete is True
    assert result.incomplete_reasons == ()


def test_search_is_case_sensitive_and_zero_matches_are_complete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write_source(root / "app.py", "Discount = 1\n")

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount"),
    )

    assert result.matches == ()
    assert result.returned_count == 0
    assert result.is_complete is True


def test_search_ignores_controlled_directories(tmp_path: Path) -> None:
    root = tmp_path / "project"
    write_source(root / "visible.py", "discount = 1\n")
    for directory in (".git", ".venv", "__pycache__", ".test-tmp"):
        write_source(root / directory / "hidden.py", "discount = 2\n")

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount"),
    )

    assert [match.path for match in result.matches] == ["visible.py"]


def test_search_accepts_single_python_file_scope(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    write_source(target, "discount = 1\n")
    write_source(root / "other.py", "discount = 2\n")

    result = search_python_code(
        root,
        target,
        SearchCodeArguments(query="discount", scope="src/app.py"),
    )

    assert [match.path for match in result.matches] == ["src/app.py"]
    assert result.searched_scope == "src/app.py"


def test_search_marks_result_limit_only_after_extra_match(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write_source(root / "app.py", "discount\ndiscount\ndiscount\n")

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount", max_results=2),
    )

    assert result.returned_count == 2
    assert result.is_complete is False
    assert result.incomplete_reasons == (
        SearchIncompleteReason.RESULT_LIMIT_REACHED,
    )


def test_search_exact_limit_remains_complete_after_full_scan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write_source(root / "app.py", "discount\ndiscount\n")

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount", max_results=2),
    )

    assert result.returned_count == 2
    assert result.is_complete is True
    assert result.incomplete_reasons == ()


def test_search_skips_file_over_byte_limit(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "large.py").write_bytes(b"discount\n" + b"x" * MAX_SEARCH_FILE_BYTES)

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount"),
    )

    assert result.matches == ()
    assert result.is_complete is False
    assert result.incomplete_reasons == (
        SearchIncompleteReason.FILE_SKIPPED,
    )


def test_search_skips_non_utf8_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "invalid.py").write_bytes(b"discount = \xff\n")

    result = search_python_code(
        root,
        root,
        SearchCodeArguments(query="discount"),
    )

    assert result.matches == ()
    assert result.is_complete is False
    assert result.incomplete_reasons == (
        SearchIncompleteReason.FILE_SKIPPED,
    )


def test_search_reports_missing_scope_as_tool_failure(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    missing = root / "missing"

    with pytest.raises(SearchScopeNotFoundError) as captured:
        search_python_code(
            root,
            missing,
            SearchCodeArguments(query="discount", scope="missing"),
        )

    assert captured.value.scope == missing
