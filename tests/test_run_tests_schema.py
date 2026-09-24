import pytest
from pydantic import ValidationError

from forgemind.schema.run_tests import (
    DEFAULT_TEST_TIMEOUT_SECONDS,
    MAX_TEST_TIMEOUT_SECONDS,
    RunTestsArguments,
    RunTestsResult,
    TestOutcome as Outcome,
)


def make_result(**overrides: object) -> RunTestsResult:
    values: dict[str, object] = {
        "runner": "pytest",
        "targets": ("tests",),
        "test_outcome": Outcome.PASSED,
        "collected": 2,
        "passed": 2,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "exit_code": 0,
        "duration_ms": 25,
        "stdout": "2 passed",
        "stderr": "",
        "is_output_truncated": False,
    }
    values.update(overrides)
    return RunTestsResult.model_validate(values)


def test_run_tests_arguments_require_explicit_targets() -> None:
    arguments = RunTestsArguments(targets=("tests",))

    assert arguments.targets == ("tests",)
    assert arguments.timeout_seconds == DEFAULT_TEST_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "targets",
    [(), ("",), ("-k", "discount")],
)
def test_run_tests_arguments_reject_unsafe_or_empty_targets(
    targets: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        RunTestsArguments(targets=targets)


def test_run_tests_arguments_reject_list_in_strict_mode() -> None:
    with pytest.raises(ValidationError):
        RunTestsArguments.model_validate({"targets": ["tests"]})


@pytest.mark.parametrize("timeout_seconds", [0, MAX_TEST_TIMEOUT_SECONDS + 1])
def test_run_tests_arguments_reject_timeout_outside_bounds(
    timeout_seconds: int,
) -> None:
    with pytest.raises(ValidationError):
        RunTestsArguments(
            targets=("tests",),
            timeout_seconds=timeout_seconds,
        )


def test_run_tests_arguments_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError) as captured:
        RunTestsArguments.model_validate(
            {"targets": ("tests",), "command": "pytest tests"}
        )

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_run_tests_result_accepts_failed_test_outcome() -> None:
    result = make_result(
        test_outcome=Outcome.FAILED,
        collected=5,
        passed=3,
        failed=2,
        exit_code=1,
    )

    assert result.test_outcome is Outcome.FAILED
    assert result.passed == 3
    assert result.failed == 2


def test_run_tests_result_requires_counts_to_equal_collected() -> None:
    with pytest.raises(ValidationError):
        make_result(collected=3, passed=2)


def test_passed_outcome_requires_collected_tests_without_failures() -> None:
    with pytest.raises(ValidationError):
        make_result(collected=0, passed=0)

    with pytest.raises(ValidationError):
        make_result(failed=1, passed=1)


def test_failed_outcome_requires_at_least_one_failed_test() -> None:
    with pytest.raises(ValidationError):
        make_result(
            test_outcome=Outcome.FAILED,
            failed=0,
        )


def test_error_outcome_requires_at_least_one_reported_error() -> None:
    result = make_result(
        test_outcome=Outcome.ERROR,
        collected=2,
        passed=1,
        errors=1,
        exit_code=2,
    )
    assert result.errors == 1

    with pytest.raises(ValidationError):
        make_result(
            test_outcome=Outcome.ERROR,
            errors=0,
        )


def test_no_tests_outcome_requires_all_counts_to_be_zero() -> None:
    result = make_result(
        test_outcome=Outcome.NO_TESTS,
        collected=0,
        passed=0,
        exit_code=5,
    )
    assert result.collected == 0

    with pytest.raises(ValidationError):
        make_result(
            test_outcome=Outcome.NO_TESTS,
            collected=1,
            passed=1,
            exit_code=5,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"test_outcome": Outcome.PASSED, "exit_code": 1},
        {
            "test_outcome": Outcome.FAILED,
            "passed": 1,
            "failed": 1,
            "exit_code": 0,
        },
        {
            "test_outcome": Outcome.ERROR,
            "passed": 1,
            "errors": 1,
            "exit_code": 0,
        },
        {
            "test_outcome": Outcome.NO_TESTS,
            "collected": 0,
            "passed": 0,
            "exit_code": 0,
        },
    ],
)
def test_run_tests_result_rejects_outcome_exit_code_conflicts(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        make_result(**overrides)
