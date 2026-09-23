from pathlib import Path

import pytest

from forgemind.runtime.project_paths import (
    PathCheckActionMismatchError,
    UnsafeProjectPathError,
    record_read_file_path_rejection,
    resolve_project_path,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def make_registered_action(
    requested_path: str,
) -> tuple[AcceptedReadFileToolAction, InMemoryObservationRegistry]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-path-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": requested_path},
        reason="读取项目中的目标文件",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def test_unsafe_path_becomes_rejected_observation_without_host_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    action, observations = make_registered_action("../secret.txt")

    with pytest.raises(UnsafeProjectPathError) as captured:
        resolve_project_path(project_root, action.arguments.path)

    rejected = record_read_file_path_rejection(
        action,
        captured.value,
        observations=observations,
    )

    assert rejected.action_id == action.action_id
    assert rejected.status == "rejected"
    assert rejected.error.code is ObservationErrorCode.PATH_OUTSIDE_PROJECT
    assert [(item.key, item.value) for item in rejected.error.details] == [
        ("requested_path", "../secret.txt")
    ]
    assert observations.get(action.action_id) is rejected


def test_path_rejection_cannot_be_attached_to_another_requested_path(
    tmp_path: Path,
) -> None:
    action, observations = make_registered_action("../secret.txt")
    mismatch = UnsafeProjectPathError(
        requested_path="../other.txt",
        project_root=(tmp_path / "project").resolve(),
        resolved_path=(tmp_path / "other.txt").resolve(),
    )

    with pytest.raises(PathCheckActionMismatchError):
        record_read_file_path_rejection(
            action,
            mismatch,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get(action.action_id)
