import pytest
from pydantic import ValidationError

from forgemind.runtime.read_file_execution import (
    ReadFileResultActionMismatchError,
    build_read_file_result_from_snapshot,
    record_read_file_success,
)
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ReadFileSuccessObservation
from forgemind.schema.read_file import ReadFileResult
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def make_success_case() -> tuple[
    AcceptedReadFileToolAction,
    InMemoryObservationRegistry,
    bytes,
]:
    content = b"price = 100\n"
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/pricing.py",
            "start_line": 1,
            "max_lines": 20,
            "expected_version": calculate_content_version(content),
        },
        reason="读取已经批准的价格代码",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions), content


def test_read_file_result_becomes_registered_success_observation() -> None:
    action, observations, content = make_success_case()
    result = build_read_file_result_from_snapshot(action, content=content)

    success = record_read_file_success(
        action,
        result,
        observations=observations,
    )

    assert success.action_id == "action-001"
    assert success.status == "success"
    assert success.result is result
    assert observations.get("action-001") is success


def test_success_observation_cannot_contain_error() -> None:
    action, _, content = make_success_case()
    result = build_read_file_result_from_snapshot(action, content=content)

    with pytest.raises(ValidationError):
        ReadFileSuccessObservation.model_validate(
            {
                "action_id": action.action_id,
                "status": "success",
                "result": result,
                "error": {"message": "成功结果不能同时声称失败"},
            }
        )


def test_success_result_must_match_the_registered_action_scope() -> None:
    action, observations, _ = make_success_case()
    mismatched_result = ReadFileResult(
        path="src/other.py",
        content="other\n",
        start_line=2,
        end_line=22,
        returned_lines=21,
        eof=True,
        version="sha256:other",
        is_truncated=False,
    )

    with pytest.raises(ReadFileResultActionMismatchError) as captured:
        record_read_file_success(
            action,
            mismatched_result,
            observations=observations,
        )

    assert captured.value.mismatched_fields == (
        "path",
        "start_line",
        "returned_lines",
        "version",
    )
    with pytest.raises(KeyError):
        observations.get(action.action_id)
