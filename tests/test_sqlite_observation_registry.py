from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    RejectedObservation,
    RunCommandSuccessObservation,
)
from forgemind.schema.run_command import RunCommandArguments, RunCommandResult
from forgemind.schema.tasks import TaskRecord
from forgemind.state.observation_registry import (
    DuplicateObservationError,
    UnknownActionIdError,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_observation_registry import (
    CorruptStoredObservationError,
    SQLiteObservationRegistry,
)
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry


def _action() -> AcceptedRunCommandToolAction:
    return AcceptedRunCommandToolAction(
        action_id="action-command-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="run_command",
        arguments=RunCommandArguments(
            program="python",
            args=("-V",),
            working_directory=".",
            timeout_seconds=30,
        ),
        reason="查看 Python 版本",
    )


def _success(action_id: str) -> RunCommandSuccessObservation:
    return RunCommandSuccessObservation(
        action_id=action_id,
        status="success",
        result=RunCommandResult(
            program="python",
            executable="C:/Python/python.exe",
            args=("-V",),
            working_directory="C:/project",
            exit_code=0,
            duration_ms=10,
            stdout="Python 3.13",
            stderr="",
            is_output_truncated=False,
        ),
    )


def _rejected(action_id: str) -> RejectedObservation:
    return RejectedObservation(
        action_id=action_id,
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户拒绝执行命令",
        ),
    )


def _registries(
    database_path: Path,
) -> tuple[SQLiteActionRegistry, SQLiteObservationRegistry]:
    tasks = SQLiteTaskRegistry(database_path)
    try:
        tasks.get("task-001")
    except KeyError:
        tasks.register(
            TaskRecord(
                task_id="task-001",
                original_request="测试 Observation 持久化",
                project_root=str(database_path.parent.resolve()),
            )
        )
    actions = SQLiteActionRegistry(database_path)
    observations = SQLiteObservationRegistry(database_path, actions)
    return actions, observations


@pytest.mark.parametrize("observation_factory", [_success, _rejected])
def test_observation_survives_registry_restart(
    tmp_path: Path,
    observation_factory,
) -> None:
    database_path = tmp_path / "state.db"
    actions, observations = _registries(database_path)
    action = _action()
    observation = observation_factory(action.action_id)
    actions.register(action)
    observations.record(observation)

    restarted_actions, restarted_observations = _registries(database_path)
    restored = restarted_observations.get(action.action_id)

    assert restarted_actions.get(action.action_id) == action
    assert restored == observation
    assert restored is not observation
    assert type(restored) is type(observation)


def test_observation_requires_persisted_action(tmp_path: Path) -> None:
    _, observations = _registries(tmp_path / "state.db")

    with pytest.raises(UnknownActionIdError):
        observations.record(_success("missing-action"))


def test_second_terminal_observation_does_not_overwrite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    actions, observations = _registries(database_path)
    action = _action()
    first = _rejected(action.action_id)
    actions.register(action)
    observations.record(first)

    with pytest.raises(DuplicateObservationError):
        observations.record(_success(action.action_id))

    assert observations.get(action.action_id) == first


def test_corrupt_observation_status_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    actions, observations = _registries(database_path)
    action = _action()
    observation = _success(action.action_id)
    actions.register(action)
    observations.record(observation)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE observations SET status = ? WHERE action_id = ?",
            ("failed", action.action_id),
        )

    with pytest.raises(CorruptStoredObservationError):
        observations.get(action.action_id)
