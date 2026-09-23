import pytest

from forgemind.runtime.read_file_execution import (
    build_read_file_result_from_snapshot,
    record_read_file_processing_failure,
)
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import FailedObservation, ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.read_file import ReadFileStartLineOutOfRangeError


def make_registered_action(
    content: bytes,
    *,
    start_line: int = 1,
) -> tuple[AcceptedReadFileToolAction, InMemoryObservationRegistry]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-read-processing-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/app.py",
            "start_line": start_line,
            "expected_version": calculate_content_version(content),
        },
        reason="读取项目文件",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def details_of(observation: FailedObservation) -> list[tuple[str, str]]:
    return [(item.key, item.value) for item in observation.error.details]


def test_invalid_utf8_becomes_failed_observation() -> None:
    content = b"\xff"
    action, observations = make_registered_action(content)

    with pytest.raises(UnicodeDecodeError) as caught:
        build_read_file_result_from_snapshot(action, content=content)

    failed = record_read_file_processing_failure(
        action,
        caught.value,
        observations=observations,
    )

    assert failed.status == "failed"
    assert failed.error.code is ObservationErrorCode.INVALID_TEXT_ENCODING
    assert details_of(failed) == [
        ("requested_path", "src/app.py"),
        ("encoding", "utf-8"),
    ]
    assert observations.get(action.action_id) is failed


def test_start_line_out_of_range_becomes_failed_observation() -> None:
    content = b"only one line\n"
    action, observations = make_registered_action(content, start_line=2)

    with pytest.raises(ReadFileStartLineOutOfRangeError) as caught:
        build_read_file_result_from_snapshot(action, content=content)

    failed = record_read_file_processing_failure(
        action,
        caught.value,
        observations=observations,
    )

    assert failed.status == "failed"
    assert failed.error.code is ObservationErrorCode.START_LINE_OUT_OF_RANGE
    assert details_of(failed) == [
        ("requested_path", "src/app.py"),
        ("start_line", "2"),
    ]
    assert observations.get(action.action_id) is failed
