from pathlib import Path

import pytest

from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.runtime.run_tests_targets import (
    InvalidTestTargetError,
    resolve_run_tests_targets,
    resolve_test_target,
)


def test_resolve_plain_test_directory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    resolved = resolve_test_target(root, "tests")

    assert resolved.requested_target == "tests"
    assert resolved.resolved_path == (root / "tests").resolve()
    assert resolved.node_suffix == ""
    assert resolved.command_argument == str((root / "tests").resolve())


def test_resolve_pytest_node_id_preserves_full_suffix(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    resolved = resolve_test_target(
        root,
        "tests/test_price.py::TestPrice::test_discount",
    )

    expected_path = (root / "tests" / "test_price.py").resolve()
    assert resolved.resolved_path == expected_path
    assert resolved.node_suffix == "::TestPrice::test_discount"
    assert resolved.command_argument == (
        f"{expected_path}::TestPrice::test_discount"
    )


@pytest.mark.parametrize("target", ["::test_discount", "tests/test_a.py::"])
def test_resolve_rejects_target_with_missing_part(
    tmp_path: Path,
    target: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(InvalidTestTargetError) as captured:
        resolve_test_target(root, target)

    assert captured.value.requested_target == target


@pytest.mark.parametrize("target", ["../outside.py", "C:/outside.py"])
def test_resolve_rejects_target_outside_project(
    tmp_path: Path,
    target: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(UnsafeProjectPathError):
        resolve_test_target(root, target)


def test_resolve_does_not_claim_safe_missing_target_exists(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    resolved = resolve_test_target(root, "tests/missing.py")

    assert resolved.resolved_path == (root / "tests" / "missing.py").resolve()
    assert resolved.resolved_path.exists() is False


def test_resolve_multiple_targets_preserves_order(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    resolved = resolve_run_tests_targets(
        root,
        ("tests/test_b.py", "tests/test_a.py::test_one"),
    )

    assert tuple(item.requested_target for item in resolved) == (
        "tests/test_b.py",
        "tests/test_a.py::test_one",
    )
