import pytest
from pydantic import ValidationError

from forgemind.runtime.versioning import (
    ReadFileVersionMismatchError,
    VersionCheckActionMismatchError,
    calculate_content_version,
    record_read_file_snapshot_failure,
    verify_read_file_snapshot_version,
)
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def make_registered_action() -> tuple[
    AcceptedReadFileToolAction,
    InMemoryObservationRegistry,
]:
    approved_content = b"price = 100\n"
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/pricing.py",
            "expected_version": calculate_content_version(approved_content),
        },
        reason="读取已经批准的文件快照",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def test_tool_snapshot_version_mismatch_becomes_failed_observation() -> None:
    action, observations = make_registered_action()

    with pytest.raises(ReadFileVersionMismatchError) as captured:
        verify_read_file_snapshot_version(
            action,
            content=b"price = 80\n",
        )

    failed = record_read_file_snapshot_failure(
        action,
        captured.value,
        observations=observations,
    )

    assert failed.action_id == "action-001"
    assert failed.status == "failed"
    assert failed.error.code is ObservationErrorCode.VERSION_MISMATCH
    assert [item.key for item in failed.error.details] == [
        "expected_version",
        "actual_version",
    ]
    assert observations.get("action-001") is failed


def test_failed_observation_cannot_contain_success_result() -> None:
    with pytest.raises(ValidationError):
        FailedObservation.model_validate(
            {
                "action_id": "action-001",
                "status": "failed",
                "error": ObservationError(
                    code=ObservationErrorCode.VERSION_MISMATCH,
                    message="文件版本已变化",
                ),
                "result": {"content": "不得返回未经批准的内容"},
            }
        )


def test_snapshot_failure_cannot_be_attached_to_another_action() -> None:
    action, observations = make_registered_action()
    mismatch = ReadFileVersionMismatchError(
        action_id="action-999",
        expected_version="sha256:v1",
        actual_version="sha256:v2",
    )

    with pytest.raises(VersionCheckActionMismatchError):
        record_read_file_snapshot_failure(
            action,
            mismatch,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get("action-001")
