from pathlib import Path

import pytest

from forgemind.runtime.command_policy import (
    InvalidProgramPolicyError,
    ProgramNotAllowedError,
    resolve_command_context,
)
from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.schema.run_command import RunCommandArguments


def arguments(
    *,
    program: str = "python",
    working_directory: str = ".",
) -> RunCommandArguments:
    return RunCommandArguments(
        program=program,
        args=("-c", "print('hello; world')", ""),
        working_directory=working_directory,
        timeout_seconds=30,
    )


def test_allowed_program_and_working_directory_resolve_to_absolute_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    executable = (tmp_path / "python.exe").resolve()

    resolved = resolve_command_context(
        project_root,
        arguments(),
        allowed_programs={"python": executable},
    )

    assert resolved.program == "python"
    assert resolved.executable == executable
    assert resolved.working_directory == project_root.resolve()


def test_resolved_command_preserves_each_argument_boundary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    executable = (tmp_path / "python.exe").resolve()

    resolved = resolve_command_context(
        project_root,
        arguments(),
        allowed_programs={"python": executable},
    )

    assert resolved.command == (
        str(executable),
        "-c",
        "print('hello; world')",
        "",
    )


def test_program_alias_must_exist_in_runtime_allowlist(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(ProgramNotAllowedError) as caught:
        resolve_command_context(
            project_root,
            arguments(program="python"),
            allowed_programs={"ruff": (tmp_path / "ruff.exe").resolve()},
        )

    assert caught.value.program == "python"


def test_runtime_policy_requires_absolute_executable_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(InvalidProgramPolicyError) as caught:
        resolve_command_context(
            project_root,
            arguments(),
            allowed_programs={"python": Path("python.exe")},
        )

    assert caught.value.program == "python"
    assert caught.value.executable == Path("python.exe")


def test_working_directory_cannot_escape_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(UnsafeProjectPathError):
        resolve_command_context(
            project_root,
            arguments(working_directory="../outside"),
            allowed_programs={
                "python": (tmp_path / "python.exe").resolve(),
            },
        )


def test_safe_missing_working_directory_is_not_claimed_to_exist(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    expected = (project_root / "missing").resolve()

    resolved = resolve_command_context(
        project_root,
        arguments(working_directory="missing"),
        allowed_programs={
            "python": (tmp_path / "python.exe").resolve(),
        },
    )

    assert resolved.working_directory == expected
    assert not resolved.working_directory.exists()
