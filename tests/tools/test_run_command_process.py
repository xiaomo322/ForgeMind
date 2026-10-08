from pathlib import Path
import subprocess
import sys

import pytest

from forgemind.runtime.command_policy import ResolvedCommandContext
from forgemind.tools import run_command as run_command_tool
from forgemind.tools.run_command import (
    MAX_COMMAND_OUTPUT_BYTES,
    CommandProcessStartError,
    CommandProcessTimeoutError,
    run_command_process,
)


def _context(
    working_directory: Path,
    *,
    args: tuple[str, ...] = ("script.py", "value with spaces", "&&"),
) -> ResolvedCommandContext:
    return ResolvedCommandContext(
        program="python",
        executable=Path(sys.executable).resolve(),
        args=args,
        working_directory=working_directory,
    )


def test_run_command_uses_argv_without_shell_interpretation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)

    def fake_run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        assert command == context.command
        assert command[-2:] == ("value with spaces", "&&")
        assert kwargs["cwd"] == context.working_directory
        assert kwargs["timeout"] == 30
        assert kwargs["check"] is False
        assert kwargs["shell"] is False

        stdout = kwargs["stdout"]
        stderr = kwargs["stderr"]
        assert hasattr(stdout, "write")
        assert hasattr(stderr, "write")
        stdout.write(b"command output")  # type: ignore[union-attr]
        stderr.write(b"command warning")  # type: ignore[union-attr]
        stdout.flush()  # type: ignore[union-attr]
        stderr.flush()  # type: ignore[union-attr]
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(run_command_tool.subprocess, "run", fake_run)

    result = run_command_process(context, timeout_seconds=30)

    assert result.exit_code == 7
    assert result.stdout == "command output"
    assert result.stderr == "command warning"
    assert result.is_output_truncated is False


def test_run_command_preserves_partial_output_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> None:
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        stdout.write(b"still running")  # type: ignore[union-attr]
        stdout.flush()  # type: ignore[union-attr]
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(run_command_tool.subprocess, "run", fake_run)

    with pytest.raises(CommandProcessTimeoutError) as caught:
        run_command_process(context, timeout_seconds=1)

    assert caught.value.timeout_seconds == 1
    assert caught.value.stdout == "still running"
    assert caught.value.duration_ms >= 0


def test_run_command_maps_process_start_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)

    def fake_run(command: tuple[str, ...], **kwargs: object) -> None:
        raise FileNotFoundError("program missing")

    monkeypatch.setattr(run_command_tool.subprocess, "run", fake_run)

    with pytest.raises(CommandProcessStartError) as caught:
        run_command_process(context, timeout_seconds=30)

    assert caught.value.error_type == "FileNotFoundError"


def test_run_command_bounds_returned_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)

    def fake_run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        stdout.write(b"x" * (MAX_COMMAND_OUTPUT_BYTES + 1))  # type: ignore[union-attr]
        stdout.flush()  # type: ignore[union-attr]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_command_tool.subprocess, "run", fake_run)

    result = run_command_process(context, timeout_seconds=30)

    assert len(result.stdout.encode("utf-8")) == MAX_COMMAND_OUTPUT_BYTES
    assert result.is_output_truncated is True


def test_run_command_executes_real_process_and_keeps_nonzero_exit_code(
    tmp_path: Path,
) -> None:
    context = _context(
        tmp_path,
        args=(
            "-c",
            (
                "import sys; print('hello'); "
                "print('warning', file=sys.stderr); raise SystemExit(7)"
            ),
        ),
    )

    result = run_command_process(context, timeout_seconds=30)

    assert result.exit_code == 7
    assert result.stdout.strip() == "hello"
    assert result.stderr.strip() == "warning"
    assert result.program == "python"
    assert result.executable == str(context.executable)
    assert result.working_directory == str(tmp_path)


def test_run_command_real_process_does_not_inherit_server_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-model-secret")
    monkeypatch.setenv("FORGEMIND_TEST_SECRET", "another-server-secret")
    context = _context(
        tmp_path,
        args=(
            "-c",
            (
                "import os; "
                "print(os.getenv('DEEPSEEK_API_KEY', 'missing')); "
                "print(os.getenv('FORGEMIND_TEST_SECRET', 'missing'))"
            ),
        ),
    )

    result = run_command_process(context, timeout_seconds=30)

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["missing", "missing"]
