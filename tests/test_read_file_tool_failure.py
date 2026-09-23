from pathlib import Path

import pytest

from forgemind.runtime.read_file_execution import (
    ReadFileToolFailureTargetMismatchError,
    record_read_file_tool_failure,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import FailedObservation, ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.read_file import (
    MAX_READ_BYTES,
    ReadFileNotFoundError,
    ReadFileSystemError,
    ReadFileTargetIsDirectoryError,
    ReadFileTooLargeError,
)


def make_registered_action() -> tuple[
    AcceptedReadFileToolAction,
    InMemoryObservationRegistry,
]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-read-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
        reason="读取项目文件",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def details_of(observation: FailedObservation) -> list[tuple[str, str]]:
    return [
        (item.key, item.value)
        for item in observation.error.details
    ]


def test_missing_file_becomes_failed_observation(tmp_path: Path) -> None:
    action, observations = make_registered_action()
    resolved_path = tmp_path / "project" / "src" / "app.py"
    failure = ReadFileNotFoundError(resolved_path, "目标文件不存在")

    failed = record_read_file_tool_failure(
        action,
        failure,
        resolved_path=resolved_path,
        observations=observations,
    )

    assert failed.status == "failed"
    assert failed.error.code is ObservationErrorCode.FILE_NOT_FOUND
    assert details_of(failed) == [("requested_path", "src/app.py")]
    assert observations.get(action.action_id) is failed


def test_directory_target_becomes_failed_observation(tmp_path: Path) -> None:
    action, observations = make_registered_action()
    resolved_path = tmp_path / "project" / "src" / "app.py"
    failure = ReadFileTargetIsDirectoryError(resolved_path, "目标是目录")

    failed = record_read_file_tool_failure(
        action,
        failure,
        resolved_path=resolved_path,
        observations=observations,
    )

    assert failed.error.code is ObservationErrorCode.TARGET_IS_DIRECTORY
    assert details_of(failed) == [("requested_path", "src/app.py")]


def test_large_file_becomes_failed_observation(tmp_path: Path) -> None:
    action, observations = make_registered_action()
    resolved_path = tmp_path / "project" / "src" / "app.py"
    failure = ReadFileTooLargeError(
        resolved_path,
        max_bytes=MAX_READ_BYTES,
        observed_bytes=MAX_READ_BYTES + 1,
    )

    failed = record_read_file_tool_failure(
        action,
        failure,
        resolved_path=resolved_path,
        observations=observations,
    )

    assert failed.error.code is ObservationErrorCode.FILE_TOO_LARGE
    assert details_of(failed) == [
        ("requested_path", "src/app.py"),
        ("max_bytes", str(MAX_READ_BYTES)),
        ("observed_bytes", str(MAX_READ_BYTES + 1)),
    ]


def test_other_os_error_becomes_failed_observation(tmp_path: Path) -> None:
    action, observations = make_registered_action()
    resolved_path = tmp_path / "project" / "src" / "app.py"
    failure = ReadFileSystemError(resolved_path, PermissionError("拒绝访问"))

    failed = record_read_file_tool_failure(
        action,
        failure,
        resolved_path=resolved_path,
        observations=observations,
    )

    assert failed.error.code is ObservationErrorCode.FILE_READ_FAILED
    assert details_of(failed) == [
        ("requested_path", "src/app.py"),
        ("error_type", "PermissionError"),
    ]


def test_tool_failure_target_must_match_resolved_action_path(
    tmp_path: Path,
) -> None:
    action, observations = make_registered_action()
    resolved_path = tmp_path / "project" / "src" / "app.py"
    failure = ReadFileNotFoundError(
        tmp_path / "project" / "src" / "other.py",
        "另一文件不存在",
    )

    with pytest.raises(ReadFileToolFailureTargetMismatchError):
        record_read_file_tool_failure(
            action,
            failure,
            resolved_path=resolved_path,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get(action.action_id)
