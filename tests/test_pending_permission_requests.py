import pytest
from pydantic import ValidationError

from forgemind.schema.permissions import (
    PendingReadFilePermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)


def test_pending_read_file_permission_request_keeps_action_snapshot() -> None:
    request = PendingReadFilePermissionRequest(
        permission_request_id="permission-request-001",
        task_id="task-001",
        action_id="action-001",
        status="pending",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/private.py",
            "start_line": 10,
            "max_lines": 50,
            "expected_version": "sha256:abc",
        },
        reason="该路径需要用户确认",
        basis_ids=("permission-policy-001",),
    )

    assert request.status == "pending"
    assert request.action_id == "action-001"
    assert request.arguments.path == "src/private.py"
    assert request.arguments.start_line == 10
    assert request.basis_ids == ("permission-policy-001",)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("status", "approved"),
        ("action_type", "ask_user"),
        ("tool_name", "edit_file"),
    ],
)
def test_pending_read_file_permission_request_rejects_wrong_route_tags(
    field: str,
    invalid_value: str,
) -> None:
    data = {
        "permission_request_id": "permission-request-001",
        "task_id": "task-001",
        "action_id": "action-001",
        "status": "pending",
        "action_type": "tool_call",
        "tool_name": "read_file",
        "arguments": {
            "path": "src/private.py",
            "expected_version": "sha256:abc",
        },
        "reason": "该路径需要用户确认",
        "basis_ids": ("permission-policy-001",),
    }
    data[field] = invalid_value

    with pytest.raises(ValidationError):
        PendingReadFilePermissionRequest.model_validate(data)


def test_pending_permission_request_requires_its_own_id() -> None:
    with pytest.raises(ValidationError):
        PendingReadFilePermissionRequest(
            permission_request_id="",
            task_id="task-001",
            action_id="action-001",
            status="pending",
            action_type="tool_call",
            tool_name="read_file",
            arguments={
                "path": "src/private.py",
                "expected_version": "sha256:abc",
            },
            reason="该路径需要用户确认",
            basis_ids=("permission-policy-001",),
        )


def test_pending_permission_request_requires_expected_file_version() -> None:
    with pytest.raises(ValidationError):
        PendingReadFilePermissionRequest(
            permission_request_id="permission-request-001",
            task_id="task-001",
            action_id="action-001",
            status="pending",
            action_type="tool_call",
            tool_name="read_file",
            arguments={"path": "src/private.py"},
            reason="授权必须绑定具体文件版本",
            basis_ids=("permission-policy-001",),
        )


@pytest.mark.parametrize(
    "decision",
    [PermissionDecision.APPROVE, PermissionDecision.REJECT],
)
def test_permission_decision_record_preserves_normalized_and_raw_decision(
    decision: PermissionDecision,
) -> None:
    record = PermissionDecisionRecord(
        permission_decision_id="permission-decision-001",
        permission_request_id="permission-request-001",
        task_id="task-001",
        action_id="action-001",
        decision=decision,
        source="user",
        raw_response="我确认这个选择",
    )

    assert record.decision is decision
    assert record.source == "user"
    assert record.raw_response == "我确认这个选择"


def test_permission_decision_rejects_permission_check_outcome() -> None:
    with pytest.raises(ValidationError):
        PermissionDecisionRecord(
            permission_decision_id="permission-decision-001",
            permission_request_id="permission-request-001",
            task_id="task-001",
            action_id="action-001",
            decision="allowed",
            source="user",
            raw_response="同意",
        )


@pytest.mark.parametrize(
    "field",
    [
        "permission_decision_id",
        "permission_request_id",
        "task_id",
        "action_id",
        "raw_response",
    ],
)
def test_permission_decision_rejects_empty_required_text(field: str) -> None:
    data = {
        "permission_decision_id": "permission-decision-001",
        "permission_request_id": "permission-request-001",
        "task_id": "task-001",
        "action_id": "action-001",
        "decision": PermissionDecision.APPROVE,
        "source": "user",
        "raw_response": "同意",
    }
    data[field] = ""

    with pytest.raises(ValidationError):
        PermissionDecisionRecord.model_validate(data)


def test_permission_decision_source_must_be_user() -> None:
    with pytest.raises(ValidationError):
        PermissionDecisionRecord(
            permission_decision_id="permission-decision-001",
            permission_request_id="permission-request-001",
            task_id="task-001",
            action_id="action-001",
            decision=PermissionDecision.APPROVE,
            source="agent",
            raw_response="Agent 推测用户会同意",
        )
