import pytest

from forgemind.runtime.versioning import (
    ReadFileExpectedVersionRequiredError,
    ReadFileVersionMismatchError,
    calculate_content_version,
    verify_approved_read_file_version,
    verify_read_file_snapshot_version,
)
from forgemind.schema.actions import AcceptedReadFileToolAction


def make_action(expected_version: str | None) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id="action-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/private.py",
            "max_lines": 50,
            "expected_version": expected_version,
        },
        reason="读取用户已批准的固定文件版本",
    )


def test_version_gate_returns_same_action_when_version_matches() -> None:
    action = make_action("sha256:v1")

    verified = verify_approved_read_file_version(
        action,
        actual_version="sha256:v1",
    )

    assert verified is action
    assert verified.arguments.max_lines == 50


def test_version_gate_rejects_changed_file_version() -> None:
    action = make_action("sha256:v1")

    with pytest.raises(ReadFileVersionMismatchError) as captured:
        verify_approved_read_file_version(
            action,
            actual_version="sha256:v2",
        )

    assert captured.value.action_id == "action-001"
    assert captured.value.expected_version == "sha256:v1"
    assert captured.value.actual_version == "sha256:v2"


def test_version_gate_rejects_approved_action_without_expected_version() -> None:
    action = make_action(None)

    with pytest.raises(ReadFileExpectedVersionRequiredError):
        verify_approved_read_file_version(
            action,
            actual_version="sha256:v1",
        )


def test_tool_snapshot_check_uses_version_of_same_bytes() -> None:
    content = b"price = 100\n"
    expected_version = calculate_content_version(content)
    action = make_action(expected_version)

    actual_version = verify_read_file_snapshot_version(
        action,
        content=content,
    )

    assert actual_version == expected_version
    assert actual_version.startswith("sha256:")


def test_tool_snapshot_check_rejects_changed_bytes() -> None:
    approved_content = b"price = 100\n"
    changed_content = b"price = 80\n"
    action = make_action(calculate_content_version(approved_content))

    with pytest.raises(ReadFileVersionMismatchError) as captured:
        verify_read_file_snapshot_version(
            action,
            content=changed_content,
        )

    assert captured.value.expected_version == calculate_content_version(
        approved_content
    )
    assert captured.value.actual_version == calculate_content_version(
        changed_content
    )


def test_tool_snapshot_check_requires_expected_version() -> None:
    action = make_action(None)

    with pytest.raises(ReadFileExpectedVersionRequiredError):
        verify_read_file_snapshot_version(
            action,
            content=b"price = 100\n",
        )
