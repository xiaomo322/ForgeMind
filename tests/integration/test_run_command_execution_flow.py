import sys
from pathlib import Path

import pytest

from forgemind.runtime import run_command_execution
from forgemind.runtime.run_command_execution import (
    RunCommandResultContextMismatchError,
    execute_run_command_action,
    record_run_command_success,
)
from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.schema.run_command import RunCommandArguments, RunCommandResult
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.run_command import (
    CommandProcessStartError,
    CommandProcessTimeoutError,
)


PYTHON_EXECUTABLE = Path(sys.executable).resolve()


def _action(
    *,
    program: str = "python",
    working_directory: str = ".",
) -> AcceptedRunCommandToolAction:
    return AcceptedRunCommandToolAction(
        action_id="action-command-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program=program,
            args=("-c", "raise SystemExit(7)"),
            working_directory=working_directory,
            timeout_seconds=30,
        ),
        reason="验证命令执行结果",
    )


def _observations(
    action: AcceptedRunCommandToolAction,
) -> InMemoryObservationRegistry:
    actions = InMemoryActionRegistry()
    actions.register(action)
    return InMemoryObservationRegistry(actions)


def _result(
    action: AcceptedRunCommandToolAction,
    executable: Path,
    working_directory: Path,
) -> RunCommandResult:
    return RunCommandResult(
        program=action.arguments.program,
        executable=str(executable),
        args=action.arguments.args,
        working_directory=str(working_directory),
        exit_code=7,
        duration_ms=10,
        stdout="",
        stderr="",
        is_output_truncated=False,
    )


@pytest.mark.parametrize(
    ("program", "working_directory", "allowed_programs", "expected_code"),
    [
        (
            "python",
            "../outside",
            {"python": PYTHON_EXECUTABLE},
            ObservationErrorCode.PATH_OUTSIDE_PROJECT,
        ),
        (
            "node",
            ".",
            {"python": PYTHON_EXECUTABLE},
            ObservationErrorCode.PROGRAM_NOT_ALLOWED,
        ),
        (
            "python",
            ".",
            {"python": Path("relative/python.exe")},
            ObservationErrorCode.INVALID_PROGRAM_POLICY,
        ),
    ],
)
def test_policy_failure_is_rejected_before_tool_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    program: str,
    working_directory: str,
    allowed_programs: dict[str, Path],
    expected_code: ObservationErrorCode,
) -> None:
    action = _action(program=program, working_directory=working_directory)
    observations = _observations(action)

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("策略拒绝后不应调用 Tool")

    monkeypatch.setattr(
        run_command_execution,
        "run_command_process",
        fail_if_called,
    )

    observation = execute_run_command_action(
        action,
        project_root=tmp_path,
        allowed_programs=allowed_programs,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is expected_code
    assert observations.get(action.action_id) is observation


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            CommandProcessStartError(FileNotFoundError("missing")),
            ObservationErrorCode.COMMAND_START_FAILED,
        ),
        (
            CommandProcessTimeoutError(
                timeout_seconds=30,
                duration_ms=30_010,
                stdout="partial output",
                stderr="",
                is_output_truncated=False,
            ),
            ObservationErrorCode.COMMAND_TIMEOUT,
        ),
    ],
)
def test_tool_failure_is_recorded_as_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: ObservationErrorCode,
) -> None:
    action = _action()
    observations = _observations(action)

    def raise_failure(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(
        run_command_execution,
        "run_command_process",
        raise_failure,
    )

    observation = execute_run_command_action(
        action,
        project_root=tmp_path,
        allowed_programs={"python": PYTHON_EXECUTABLE},
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is expected_code
    assert observations.get(action.action_id) is observation


def test_nonzero_exit_code_is_recorded_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = _action()
    observations = _observations(action)
    executable = PYTHON_EXECUTABLE
    expected = _result(action, executable, tmp_path.resolve())
    monkeypatch.setattr(
        run_command_execution,
        "run_command_process",
        lambda *args, **kwargs: expected,
    )

    observation = execute_run_command_action(
        action,
        project_root=tmp_path,
        allowed_programs={"python": executable},
        observations=observations,
    )

    assert observation.status == "success"
    assert observation.result.exit_code == 7
    assert observations.get(action.action_id) is observation


def test_success_result_must_match_resolved_context(tmp_path: Path) -> None:
    action = _action()
    observations = _observations(action)
    context = run_command_execution.resolve_command_context(
        tmp_path,
        action.arguments,
        allowed_programs={"python": PYTHON_EXECUTABLE},
    )
    mismatched = _result(
        action,
        (tmp_path / "other-python").resolve(),
        tmp_path.resolve(),
    )

    with pytest.raises(RunCommandResultContextMismatchError):
        record_run_command_success(
            action,
            context,
            mismatched,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get(action.action_id)
