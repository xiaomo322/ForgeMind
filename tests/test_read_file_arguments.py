import pytest
from pydantic import ValidationError

from forgemind.schema.read_file import ReadFileArguments


def test_read_file_arguments_normalizes_omitted_values() -> None:
    arguments = ReadFileArguments(path="src/app.py")

    assert arguments.model_dump() == {
        "path": "src/app.py",
        "start_line": 1,
        "max_lines": 200,
        "expected_version": None,
    }


def test_read_file_arguments_rejects_non_positive_start_line() -> None:
    with pytest.raises(ValidationError) as captured:
        ReadFileArguments(path="src/app.py", start_line=0)

    assert captured.value.errors()[0]["type"] == "greater_than_equal"


@pytest.mark.parametrize(
    ("max_lines", "error_type"),
    [
        (0, "greater_than_equal"),
        (1001, "less_than_equal"),
    ],
)
def test_read_file_arguments_rejects_max_lines_outside_limits(
    max_lines: int,
    error_type: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        ReadFileArguments(path="src/app.py", max_lines=max_lines)

    assert captured.value.errors()[0]["type"] == error_type


@pytest.mark.parametrize(
    "invalid_arguments",
    [
        {"path": ""},
        {"path": "src/app.py", "expected_version": ""},
    ],
)
def test_read_file_arguments_rejects_empty_required_values(
    invalid_arguments: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as captured:
        ReadFileArguments(**invalid_arguments)

    assert captured.value.errors()[0]["type"] == "string_too_short"
