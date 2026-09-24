from pathlib import Path
import subprocess
import sys

import pytest

from forgemind.runtime.run_tests_targets import (
    ResolvedTestTarget,
    resolve_run_tests_targets,
)
from forgemind.schema.run_tests import RunTestsArguments, TestOutcome as Outcome
from forgemind.tools import run_tests as run_tests_tool
from forgemind.tools.run_tests import (
    MAX_TEST_OUTPUT_BYTES,
    PytestProcessStartError,
    PytestProcessTimeoutError,
    PytestReportTooLargeError,
    PytestReportUnavailableError,
    RunTestsTargetMismatchError,
    run_pytest,
)


def resolved_target(project_root: Path) -> ResolvedTestTarget:
    return ResolvedTestTarget(
        requested_target="tests/test_price.py::test_discount",
        resolved_path=(project_root / "tests" / "test_price.py").resolve(),
        node_suffix="::test_discount",
    )


def report_argument(command: tuple[str, ...]) -> Path:
    prefix = "--junitxml="
    return Path(next(item[len(prefix):] for item in command if item.startswith(prefix)))


def test_run_pytest_uses_controlled_command_and_returns_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = RunTestsArguments(
        targets=("tests/test_price.py::test_discount",),
        timeout_seconds=30,
    )
    target = resolved_target(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert command[:3] == (sys.executable, "-m", "pytest")
        assert command[-1] == target.command_argument
        assert kwargs["cwd"] == tmp_path.resolve()
        assert kwargs["timeout"] == 30
        assert kwargs["check"] is False
        assert kwargs["shell"] is False

        stdout = kwargs["stdout"]
        stderr = kwargs["stderr"]
        assert hasattr(stdout, "write")
        assert hasattr(stderr, "write")
        stdout.write(b"pytest output")  # type: ignore[union-attr]
        stderr.write(b"")  # type: ignore[union-attr]
        stdout.flush()  # type: ignore[union-attr]
        report_argument(command).write_bytes(
            b'<testsuite tests="1" failures="0" errors="0" skipped="0" />'
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_tests_tool.subprocess, "run", fake_run)

    result = run_pytest(tmp_path, arguments, (target,))

    assert result.test_outcome is Outcome.PASSED
    assert result.passed == 1
    assert result.stdout == "pytest output"
    assert result.is_output_truncated is False


def test_run_pytest_rejects_resolved_target_mismatch(tmp_path: Path) -> None:
    arguments = RunTestsArguments(targets=("tests/test_other.py",))

    with pytest.raises(RunTestsTargetMismatchError):
        run_pytest(tmp_path, arguments, (resolved_target(tmp_path),))


def test_run_pytest_preserves_partial_output_when_timeout_occurs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = RunTestsArguments(
        targets=("tests/test_price.py::test_discount",),
        timeout_seconds=1,
    )
    target = resolved_target(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> None:
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        stdout.write(b"still running")  # type: ignore[union-attr]
        stdout.flush()  # type: ignore[union-attr]
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(run_tests_tool.subprocess, "run", fake_run)

    with pytest.raises(PytestProcessTimeoutError) as caught:
        run_pytest(tmp_path, arguments, (target,))

    assert caught.value.timeout_seconds == 1
    assert caught.value.stdout == "still running"
    assert caught.value.duration_ms >= 0


def test_run_pytest_maps_process_start_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = RunTestsArguments(
        targets=("tests/test_price.py::test_discount",),
    )
    target = resolved_target(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> None:
        raise FileNotFoundError("python missing")

    monkeypatch.setattr(run_tests_tool.subprocess, "run", fake_run)

    with pytest.raises(PytestProcessStartError) as caught:
        run_pytest(tmp_path, arguments, (target,))

    assert caught.value.error_type == "FileNotFoundError"


def test_run_pytest_reports_missing_junit_with_real_process_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = RunTestsArguments(
        targets=("tests/test_price.py::test_discount",),
    )
    target = resolved_target(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        stderr = kwargs["stderr"]
        assert hasattr(stderr, "write")
        stderr.write(b"internal error")  # type: ignore[union-attr]
        stderr.flush()  # type: ignore[union-attr]
        return subprocess.CompletedProcess(command, 3)

    monkeypatch.setattr(run_tests_tool.subprocess, "run", fake_run)

    with pytest.raises(PytestReportUnavailableError) as caught:
        run_pytest(tmp_path, arguments, (target,))

    assert caught.value.exit_code == 3
    assert caught.value.stderr == "internal error"


def test_run_pytest_bounds_stdout_and_marks_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = RunTestsArguments(
        targets=("tests/test_price.py::test_discount",),
    )
    target = resolved_target(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        stdout.write(b"x" * (MAX_TEST_OUTPUT_BYTES + 1))  # type: ignore[union-attr]
        stdout.flush()  # type: ignore[union-attr]
        report_argument(command).write_bytes(
            b'<testsuite tests="1" failures="0" errors="0" skipped="0" />'
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_tests_tool.subprocess, "run", fake_run)

    result = run_pytest(tmp_path, arguments, (target,))

    assert len(result.stdout.encode("utf-8")) == MAX_TEST_OUTPUT_BYTES
    assert result.is_output_truncated is True


@pytest.mark.parametrize(
    ("test_source", "expected_outcome", "expected_exit_code"),
    [
        ("def test_sample():\n    assert True\n", Outcome.PASSED, 0),
        ("def test_sample():\n    assert False\n", Outcome.FAILED, 1),
        ("def test_broken(:\n    pass\n", Outcome.ERROR, 2),
        ("VALUE = 1\n", Outcome.NO_TESTS, 5),
    ],
)
def test_run_pytest_executes_real_pytest_and_parses_its_report(
    tmp_path: Path,
    test_source: str,
    expected_outcome: Outcome,
    expected_exit_code: int,
) -> None:
    tests_directory = tmp_path / "tests"
    tests_directory.mkdir()
    (tests_directory / "test_sample.py").write_text(
        test_source,
        encoding="utf-8",
    )
    arguments = RunTestsArguments(
        targets=("tests/test_sample.py",),
        timeout_seconds=30,
    )
    targets = resolve_run_tests_targets(tmp_path, arguments.targets)

    result = run_pytest(tmp_path, arguments, targets)

    assert result.test_outcome is expected_outcome
    assert result.exit_code == expected_exit_code
    assert result.targets == arguments.targets


def test_run_pytest_rejects_junit_report_over_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = RunTestsArguments(
        targets=("tests/test_price.py::test_discount",),
    )
    target = resolved_target(tmp_path)
    monkeypatch.setattr(run_tests_tool, "MAX_JUNIT_XML_BYTES", 16)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        report_argument(command).write_bytes(b"x" * 17)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_tests_tool.subprocess, "run", fake_run)

    with pytest.raises(PytestReportTooLargeError) as caught:
        run_pytest(tmp_path, arguments, (target,))

    assert caught.value.max_bytes == 16
