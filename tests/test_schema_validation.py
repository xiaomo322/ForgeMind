import pytest
from pydantic import ValidationError

from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.validation import SchemaErrorCode, map_validation_error


def test_validation_error_maps_all_pydantic_errors_to_stable_codes() -> None:
    with pytest.raises(ValidationError) as captured:
        ReadFileArguments.model_validate(
            {
                "path": "src/app.py",
                "start_line": "1",
                "recursive": True,
            }
        )

    issues = map_validation_error(captured.value)
    codes_by_path = {issue.field_path: issue.code for issue in issues}

    assert codes_by_path == {
        ("start_line",): SchemaErrorCode.INVALID_TYPE,
        ("recursive",): SchemaErrorCode.UNKNOWN_FIELD,
    }


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({}, SchemaErrorCode.MISSING_FIELD),
        ({"path": 123}, SchemaErrorCode.INVALID_TYPE),
    ],
)
def test_validation_error_distinguishes_missing_and_wrong_type(
    payload: dict[str, object],
    expected_code: SchemaErrorCode,
) -> None:
    with pytest.raises(ValidationError) as captured:
        ReadFileArguments.model_validate(payload)

    issues = map_validation_error(captured.value)

    assert len(issues) == 1
    assert issues[0].field_path == ("path",)
    assert issues[0].code is expected_code


def test_validation_error_maps_constraint_failure_to_invalid_value() -> None:
    with pytest.raises(ValidationError) as captured:
        ReadFileArguments(path="src/app.py", start_line=0)

    issues = map_validation_error(captured.value)

    assert len(issues) == 1
    assert issues[0].field_path == ("start_line",)
    assert issues[0].code is SchemaErrorCode.INVALID_VALUE
