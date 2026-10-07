import pytest

from forgemind.schema.run_tests import RunTestsArguments, TestOutcome as Outcome
from forgemind.tools.run_tests import (
    InvalidPytestReportError,
    build_run_tests_result_from_junit,
    parse_pytest_junit_counts,
)


def junit_report(
    *,
    tests: int,
    failures: int,
    errors: int,
    skipped: int,
) -> bytes:
    return (
        '<testsuites name="pytest tests">'
        f'<testsuite name="pytest" tests="{tests}" '
        f'failures="{failures}" errors="{errors}" skipped="{skipped}" />'
        "</testsuites>"
    ).encode()


def build_result(junit_xml: bytes, exit_code: int):
    return build_run_tests_result_from_junit(
        RunTestsArguments(targets=("tests",)),
        junit_xml=junit_xml,
        exit_code=exit_code,
        duration_ms=25,
        stdout="pytest output",
        stderr="",
        is_output_truncated=False,
    )


def test_parser_builds_passed_result_from_complete_report() -> None:
    result = build_result(
        junit_report(tests=3, failures=0, errors=0, skipped=1),
        exit_code=0,
    )

    assert result.test_outcome is Outcome.PASSED
    assert result.collected == 3
    assert result.passed == 2
    assert result.skipped == 1


def test_parser_builds_failed_result_from_test_failures() -> None:
    result = build_result(
        junit_report(tests=5, failures=2, errors=0, skipped=0),
        exit_code=1,
    )

    assert result.test_outcome is Outcome.FAILED
    assert result.passed == 3
    assert result.failed == 2


def test_parser_gives_errors_precedence_over_failures() -> None:
    result = build_result(
        junit_report(tests=4, failures=1, errors=1, skipped=0),
        exit_code=1,
    )

    assert result.test_outcome is Outcome.ERROR
    assert result.failed == 1
    assert result.errors == 1


def test_parser_builds_no_tests_result() -> None:
    result = build_result(
        junit_report(tests=0, failures=0, errors=0, skipped=0),
        exit_code=5,
    )

    assert result.test_outcome is Outcome.NO_TESTS
    assert result.collected == 0


@pytest.mark.parametrize(
    "junit_xml",
    [
        b"<testsuites>",
        b"<unexpected />",
        b'<testsuite tests="1" errors="0" skipped="0" />',
        b'<testsuite tests="one" failures="0" errors="0" skipped="0" />',
        b'<testsuite tests="1" failures="2" errors="0" skipped="0" />',
        b'<testsuite tests="-1" failures="0" errors="0" skipped="0" />',
    ],
)
def test_parser_rejects_invalid_or_inconsistent_report(
    junit_xml: bytes,
) -> None:
    with pytest.raises(InvalidPytestReportError):
        parse_pytest_junit_counts(junit_xml)


def test_parser_aggregates_multiple_top_level_suites() -> None:
    report = b"""
    <testsuites>
      <testsuite tests="2" failures="1" errors="0" skipped="0" />
      <testsuite tests="3" failures="0" errors="1" skipped="1" />
    </testsuites>
    """

    counts = parse_pytest_junit_counts(report)

    assert counts.collected == 5
    assert counts.passed == 2
    assert counts.failed == 1
    assert counts.errors == 1
    assert counts.skipped == 1
