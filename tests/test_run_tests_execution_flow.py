from pathlib import Path

import pytest

from forgemind.runtime import run_tests_execution
from forgemind.runtime.run_tests_execution import (
    RunTestsResultActionMismatchError,
    execute_run_tests_action,
)
from forgemind.schema.actions import AcceptedRunTestsToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.run_tests import (
    RunTestsArguments,
    RunTestsResult,
    TestOutcome as Outcome,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.run_tests import (
    PytestProcessStartError,
    PytestProcessTimeoutError,
    PytestReportInvalidError,
    PytestReportTooLargeError,
    PytestReportUnavailableError,
)


def make_action(
    targets: tuple[str, ...] = ("tests/test_price.py",),
) -> AcceptedRunTestsToolAction:
    return AcceptedRunTestsToolAction(
        action_id="action-run-tests-1",
        task_id="task-1",
        action_type="tool_call",
        tool_name="run_tests",
        arguments=RunTestsArguments(targets=targets, timeout_seconds=30),
        reason="验证折扣修改",
    )


def make_registries(
    action: AcceptedRunTestsToolAction,
) -> tuple[InMemoryActionRegistry, InMemoryObservationRegistry]:
    actions = InMemoryActionRegistry()
    actions.register(action)
    return actions, InMemoryObservationRegistry(actions)


def failed_result(action: AcceptedRunTestsToolAction) -> RunTestsResult:
    return RunTestsResult(
        runner="pytest",
        targets=action.arguments.targets,
        test_outcome=Outcome.FAILED,
        collected=2,
        passed=1,
        failed=1,
        errors=0,
        skipped=0,
        exit_code=1,
        duration_ms=25,
        stdout="1 failed, 1 passed",
        stderr="",
        is_output_truncated=False,
    )


def detail_map(observation: object) -> dict[str, str]:
    error = getattr(observation, "error")
    return {detail.key: detail.value for detail in error.details}


def test_test_failures_still_record_success_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = make_action()
    _, observations = make_registries(action)
    monkeypatch.setattr(
        run_tests_execution,
        "run_pytest",
        lambda *args, **kwargs: failed_result(action),
    )

    observation = execute_run_tests_action(
        action,
        project_root=tmp_path,
        observations=observations,
    )

    assert observation.status == "success"
    assert observation.result.test_outcome == "failed"
    assert observations.get(action.action_id) is observation


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        ("../outside.py", ObservationErrorCode.PATH_OUTSIDE_PROJECT),
        ("tests/test_price.py::", ObservationErrorCode.INVALID_TEST_TARGET),
    ],
)
def test_invalid_target_is_rejected_before_tool_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    expected_code: ObservationErrorCode,
) -> None:
    action = make_action((target,))
    _, observations = make_registries(action)

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("目标被拒绝后不应调用 Tool")

    monkeypatch.setattr(run_tests_execution, "run_pytest", fail_if_called)

    observation = execute_run_tests_action(
        action,
        project_root=tmp_path,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is expected_code
    assert observations.get(action.action_id) is observation


def test_timeout_records_partial_process_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = make_action()
    _, observations = make_registries(action)

    def raise_timeout(*args: object, **kwargs: object) -> None:
        raise PytestProcessTimeoutError(
            timeout_seconds=30,
            duration_ms=30_015,
            stdout="collected 2 items",
            stderr="",
            is_output_truncated=False,
        )

    monkeypatch.setattr(run_tests_execution, "run_pytest", raise_timeout)

    observation = execute_run_tests_action(
        action,
        project_root=tmp_path,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.TEST_RUNNER_TIMEOUT
    assert detail_map(observation)["stdout"] == "collected 2 items"
    assert detail_map(observation)["duration_ms"] == "30015"


def test_missing_report_records_exit_code_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = make_action()
    _, observations = make_registries(action)

    def raise_missing_report(*args: object, **kwargs: object) -> None:
        raise PytestReportUnavailableError(
            exit_code=3,
            duration_ms=12,
            stdout="",
            stderr="internal error",
            is_output_truncated=False,
        )

    monkeypatch.setattr(
        run_tests_execution,
        "run_pytest",
        raise_missing_report,
    )

    observation = execute_run_tests_action(
        action,
        project_root=tmp_path,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.TEST_REPORT_UNAVAILABLE
    assert detail_map(observation)["exit_code"] == "3"
    assert detail_map(observation)["stderr"] == "internal error"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            PytestProcessStartError(FileNotFoundError("pytest missing")),
            ObservationErrorCode.TEST_RUNNER_START_FAILED,
        ),
        (
            PytestReportTooLargeError(
                max_bytes=1024,
                exit_code=0,
                duration_ms=20,
                stdout="tests finished",
                stderr="",
                is_output_truncated=False,
            ),
            ObservationErrorCode.TEST_REPORT_TOO_LARGE,
        ),
        (
            PytestReportInvalidError(
                cause=ValueError("bad report"),
                exit_code=1,
                duration_ms=21,
                stdout="invalid report",
                stderr="",
                is_output_truncated=False,
            ),
            ObservationErrorCode.TEST_REPORT_INVALID,
        ),
    ],
)
def test_other_tool_failures_are_recorded_with_stable_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: ObservationErrorCode,
) -> None:
    action = make_action()
    _, observations = make_registries(action)

    def raise_failure(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(run_tests_execution, "run_pytest", raise_failure)

    observation = execute_run_tests_action(
        action,
        project_root=tmp_path,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is expected_code
    assert observations.get(action.action_id) is observation


def test_success_result_must_match_accepted_action_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = make_action()
    _, observations = make_registries(action)
    mismatched = RunTestsResult(
        runner="pytest",
        targets=("tests/test_other.py",),
        test_outcome=Outcome.PASSED,
        collected=1,
        passed=1,
        failed=0,
        errors=0,
        skipped=0,
        exit_code=0,
        duration_ms=10,
        stdout="1 passed",
        stderr="",
        is_output_truncated=False,
    )
    monkeypatch.setattr(
        run_tests_execution,
        "run_pytest",
        lambda *args, **kwargs: mismatched,
    )

    with pytest.raises(RunTestsResultActionMismatchError):
        execute_run_tests_action(
            action,
            project_root=tmp_path,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get(action.action_id)
