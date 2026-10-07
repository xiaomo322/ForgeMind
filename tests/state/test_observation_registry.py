import pytest

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    RejectedObservation,
)
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import (
    DuplicateObservationError,
    InMemoryObservationRegistry,
    UnknownActionIdError,
)


def test_rejected_observation_is_appended_without_deleting_action() -> None:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction.model_validate(
        {
            "action_id": "action-001",
            "task_id": "task-001",
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )
    actions.register(action)
    observations = InMemoryObservationRegistry(actions)
    rejected = RejectedObservation(
        action_id="action-001",
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户拒绝授权",
        ),
    )

    observations.record(rejected)

    assert actions.get("action-001") is action
    assert observations.get("action-001") is rejected


def test_observation_registry_rejects_unknown_action_id() -> None:
    observations = InMemoryObservationRegistry(InMemoryActionRegistry())
    rejected = RejectedObservation(
        action_id="missing-action",
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户拒绝授权",
        ),
    )

    with pytest.raises(UnknownActionIdError):
        observations.record(rejected)


def test_observation_registry_rejects_duplicate_without_overwrite() -> None:
    actions = InMemoryActionRegistry()
    actions.register(
        AcceptedReadFileToolAction.model_validate(
            {
                "action_id": "action-001",
                "task_id": "task-001",
                "action_type": "tool_call",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py"},
                "reason": "读取价格计算逻辑",
            }
        )
    )
    observations = InMemoryObservationRegistry(actions)
    original = RejectedObservation(
        action_id="action-001",
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="第一次拒绝记录",
        ),
    )
    replacement = RejectedObservation(
        action_id="action-001",
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="不应覆盖原记录",
        ),
    )
    observations.record(original)

    with pytest.raises(DuplicateObservationError):
        observations.record(replacement)

    assert observations.get("action-001") is original
