from pathlib import Path

import pytest

from forgemind.runtime import permission_execution
from forgemind.runtime.permission_execution import approve_process_permission
from forgemind.runtime.run_command_handler import handle_run_command_decision
from forgemind.runtime.run_tests_handler import handle_run_tests_decision
from forgemind.schema.decisions import (
    RunCommandToolCallDecision,
    RunTestsToolCallDecision,
)
from forgemind.schema.observations import (
    RunCommandSuccessObservation,
    RunTestsSuccessObservation,
)
from forgemind.schema.run_command import RunCommandResult
from forgemind.schema.run_tests import RunTestsResult, TestOutcome as Outcome
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _state(tmp_path: Path) -> SQLiteForgeMindState:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    state.create_task(
        TaskRecord(
            task_id="task-001",
            original_request="验证项目",
            project_root=str(tmp_path.resolve()),
        ),
        TaskStatusRecord(
            task_status_id="status-001",
            task_id="task-001",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )
    return state


@pytest.mark.parametrize("tool_name", ["run_tests", "run_command"])
def test_process_decision_enters_waiting_without_execution(
    tmp_path: Path,
    tool_name: str,
) -> None:
    state = _state(tmp_path)
    if tool_name == "run_tests":
        result = handle_run_tests_decision(
            RunTestsToolCallDecision(
                action_type="tool_call",
                tool_name="run_tests",
                arguments={"targets": ("tests",), "timeout_seconds": 30},
                reason="运行测试",
            ),
            task_id="task-001",
            state=state,
            next_action_id=lambda: "action-001",
            next_permission_request_id=lambda: "request-001",
            next_task_status_id=lambda: "status-002",
        )
    else:
        result = handle_run_command_decision(
            RunCommandToolCallDecision(
                action_type="tool_call",
                tool_name="run_command",
                arguments={
                    "program": "python",
                    "args": ("-V",),
                    "working_directory": ".",
                    "timeout_seconds": 30,
                },
                reason="查看 Python 版本",
            ),
            task_id="task-001",
            state=state,
            next_action_id=lambda: "action-001",
            next_permission_request_id=lambda: "request-001",
            next_task_status_id=lambda: "status-002",
        )

    assert result.permission_request.tool_name == tool_name
    assert state.task_statuses.get_current("task-001").status is TaskStatus.WAITING_USER
    assert state.observations.get_optional("action-001") is None


@pytest.mark.parametrize("tool_name", ["run_tests", "run_command"])
def test_approval_records_real_process_observation_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    state = _state(tmp_path)
    if tool_name == "run_tests":
        waiting = handle_run_tests_decision(
            RunTestsToolCallDecision(
                action_type="tool_call",
                tool_name="run_tests",
                arguments={"targets": ("tests",), "timeout_seconds": 30},
                reason="运行测试",
            ),
            task_id="task-001",
            state=state,
            next_action_id=lambda: "action-001",
            next_permission_request_id=lambda: "request-001",
            next_task_status_id=lambda: "status-002",
        )

        def fake_tests(action, **kwargs):
            observation = RunTestsSuccessObservation(
                action_id=action.action_id,
                status="success",
                result=RunTestsResult(
                    runner="pytest",
                    targets=action.arguments.targets,
                    test_outcome=Outcome.FAILED,
                    collected=1,
                    passed=0,
                    failed=1,
                    errors=0,
                    skipped=0,
                    exit_code=1,
                    duration_ms=5,
                    stdout="1 failed",
                    stderr="",
                    is_output_truncated=False,
                ),
            )
            kwargs["observations"].record(observation)
            return observation

        monkeypatch.setattr(permission_execution, "execute_run_tests_action", fake_tests)
    else:
        waiting = handle_run_command_decision(
            RunCommandToolCallDecision(
                action_type="tool_call",
                tool_name="run_command",
                arguments={
                    "program": "python",
                    "args": ("-V",),
                    "working_directory": ".",
                    "timeout_seconds": 30,
                },
                reason="查看 Python 版本",
            ),
            task_id="task-001",
            state=state,
            next_action_id=lambda: "action-001",
            next_permission_request_id=lambda: "request-001",
            next_task_status_id=lambda: "status-002",
        )

        def fake_command(action, **kwargs):
            observation = RunCommandSuccessObservation(
                action_id=action.action_id,
                status="success",
                result=RunCommandResult(
                    program="python",
                    executable=str(Path("C:/Python/python.exe")),
                    args=action.arguments.args,
                    working_directory=str(tmp_path.resolve()),
                    exit_code=7,
                    duration_ms=4,
                    stdout="",
                    stderr="",
                    is_output_truncated=False,
                ),
            )
            kwargs["observations"].record(observation)
            return observation

        monkeypatch.setattr(permission_execution, "execute_run_command_action", fake_command)

    result = approve_process_permission(
        task_id="task-001",
        permission_request_id=waiting.permission_request.permission_request_id,
        raw_response="同意执行",
        state=state,
        allowed_programs={"python": Path("C:/Python/python.exe")},
        next_permission_decision_id=lambda: "decision-001",
        next_executing_status_id=lambda: "status-003",
        next_running_status_id=lambda: "status-004",
    )

    assert result.observation.status == "success"
    assert state.task_statuses.get_current("task-001").status is TaskStatus.RUNNING
    assert state.get_task_view("task-001").actions[0].permission_decision == result.decision
