import pytest
from pydantic import ValidationError

from forgemind.schema.run_command import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    MAX_COMMAND_TIMEOUT_SECONDS,
    RunCommandArguments,
    RunCommandResult,
)


def valid_result_data() -> dict[str, object]:
    return {
        "program": "python",
        "executable": "F:/python/python.exe",
        "args": ("-m", "compileall", "src"),
        "working_directory": ".",
        "exit_code": 0,
        "duration_ms": 25,
        "stdout": "Listing 'src'...",
        "stderr": "",
        "is_output_truncated": False,
    }


def test_arguments_keep_program_args_and_explicit_working_directory() -> None:
    arguments = RunCommandArguments(
        program="python",
        args=("-m", "compileall", "src"),
        working_directory=".",
    )

    assert arguments.program == "python"
    assert arguments.args == ("-m", "compileall", "src")
    assert arguments.working_directory == "."
    assert arguments.timeout_seconds == DEFAULT_COMMAND_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "program",
    [
        "../python",
        "bin/python",
        r"C:\Python\python.exe",
        "python -m pytest",
        "python;remove",
        "$(python)",
    ],
)
def test_arguments_reject_path_or_shell_like_program(program: str) -> None:
    with pytest.raises(ValidationError):
        RunCommandArguments(
            program=program,
            working_directory=".",
        )


def test_arguments_allow_empty_or_space_containing_individual_args() -> None:
    arguments = RunCommandArguments(
        program="python",
        args=("-c", "print('hello world')", ""),
        working_directory=".",
    )

    assert arguments.args[-1] == ""
    assert arguments.args[1] == "print('hello world')"


def test_arguments_require_explicit_non_empty_working_directory() -> None:
    with pytest.raises(ValidationError):
        RunCommandArguments(program="python", working_directory="")


@pytest.mark.parametrize(
    "timeout_seconds",
    [0, MAX_COMMAND_TIMEOUT_SECONDS + 1],
)
def test_arguments_reject_timeout_outside_bounds(
    timeout_seconds: int,
) -> None:
    with pytest.raises(ValidationError):
        RunCommandArguments(
            program="python",
            working_directory=".",
            timeout_seconds=timeout_seconds,
        )


def test_arguments_strict_mode_rejects_list_args_and_boolean_timeout() -> None:
    with pytest.raises(ValidationError):
        RunCommandArguments.model_validate(
            {
                "program": "python",
                "args": ["-m", "compileall"],
                "working_directory": ".",
                "timeout_seconds": True,
            }
        )


def test_result_preserves_nonzero_exit_as_completed_process_fact() -> None:
    data = valid_result_data()
    data["exit_code"] = 2
    data["stderr"] = "usage error"

    result = RunCommandResult.model_validate(data)

    assert result.exit_code == 2
    assert result.stderr == "usage error"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_ms", -1),
        ("is_output_truncated", 0),
        ("args", ["--version"]),
    ],
)
def test_result_rejects_invalid_or_coerced_fields(
    field: str,
    value: object,
) -> None:
    data = valid_result_data()
    data[field] = value

    with pytest.raises(ValidationError):
        RunCommandResult.model_validate(data)
