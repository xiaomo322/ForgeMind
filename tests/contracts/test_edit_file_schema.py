import pytest
from pydantic import ValidationError

from forgemind.schema.edit_file import EditFileArguments, EditFileResult


def valid_arguments_data() -> dict[str, object]:
    return {
        "path": "src/app.py",
        "old_text": "discount = 1\n",
        "new_text": "discount = 2\n",
        "expected_version": "sha256:abc",
    }


def test_edit_file_arguments_keep_explicit_empty_new_text() -> None:
    data = valid_arguments_data()
    data["new_text"] = ""

    arguments = EditFileArguments.model_validate(data)

    assert arguments.new_text == ""


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("path", ""),
        ("old_text", ""),
        ("expected_version", ""),
        ("path", 123),
        ("old_text", 123),
        ("new_text", None),
        ("expected_version", 123),
    ],
)
def test_edit_file_arguments_reject_invalid_values(
    field: str,
    invalid_value: object,
) -> None:
    data = valid_arguments_data()
    data[field] = invalid_value

    with pytest.raises(ValidationError):
        EditFileArguments.model_validate(data)


@pytest.mark.parametrize("missing_field", ["new_text", "expected_version"])
def test_edit_file_arguments_require_explicit_fields(
    missing_field: str,
) -> None:
    data = valid_arguments_data()
    del data[missing_field]

    with pytest.raises(ValidationError):
        EditFileArguments.model_validate(data)


def test_edit_file_arguments_reject_unknown_field() -> None:
    data = valid_arguments_data()
    data["replace_all"] = True

    with pytest.raises(ValidationError):
        EditFileArguments.model_validate(data)


def test_edit_file_result_accepts_one_real_change() -> None:
    result = EditFileResult(
        path="src/app.py",
        before_version="sha256:before",
        after_version="sha256:after",
        replacement_count=1,
        diff="--- src/app.py.before\n+++ src/app.py.after\n",
    )

    assert result.replacement_count == 1


def test_edit_file_result_rejects_equal_versions() -> None:
    with pytest.raises(ValidationError):
        EditFileResult(
            path="src/app.py",
            before_version="sha256:same",
            after_version="sha256:same",
            replacement_count=1,
            diff="--- before\n+++ after\n",
        )


@pytest.mark.parametrize("replacement_count", [0, 2, "1"])
def test_edit_file_result_requires_exactly_one_replacement(
    replacement_count: object,
) -> None:
    with pytest.raises(ValidationError):
        EditFileResult(
            path="src/app.py",
            before_version="sha256:before",
            after_version="sha256:after",
            replacement_count=replacement_count,
            diff="--- before\n+++ after\n",
        )


def test_edit_file_result_requires_nonempty_diff() -> None:
    with pytest.raises(ValidationError):
        EditFileResult(
            path="src/app.py",
            before_version="sha256:before",
            after_version="sha256:after",
            replacement_count=1,
            diff="",
        )
