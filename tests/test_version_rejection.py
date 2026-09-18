import pytest

from forgemind.runtime.versioning import (
    ReadFileVersionMismatchError,
    VersionCheckActionMismatchError,
    record_read_file_version_rejection,
    verify_approved_read_file_version,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def make_registered_action() -> tuple[
    AcceptedReadFileToolAction,
    InMemoryObservationRegistry,
]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/private.py",
            "expected_version": "sha256:v1",
        },
        reason="读取已经批准的文件版本",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def test_runtime_version_mismatch_becomes_rejected_observation() -> None:
    action, observations = make_registered_action()

    with pytest.raises(ReadFileVersionMismatchError) as captured:
        verify_approved_read_file_version(
            action,
            actual_version="sha256:v2",
        )

    rejected = record_read_file_version_rejection(
        action,
        captured.value,
        observations=observations,
    )

    assert rejected.action_id == "action-001"
    assert rejected.status == "rejected"
    assert rejected.error.code is ObservationErrorCode.VERSION_MISMATCH
    assert [(item.key, item.value) for item in rejected.error.details] == [
        ("expected_version", "sha256:v1"),
        ("actual_version", "sha256:v2"),
    ]
    assert observations.get("action-001") is rejected


def test_version_rejection_cannot_be_attached_to_another_action() -> None:
    action, observations = make_registered_action()
    mismatch = ReadFileVersionMismatchError(
        action_id="action-999",
        expected_version="sha256:v1",
        actual_version="sha256:v2",
    )

    with pytest.raises(VersionCheckActionMismatchError):
        record_read_file_version_rejection(
            action,
            mismatch,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get("action-001")
