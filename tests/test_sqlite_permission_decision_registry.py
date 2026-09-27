from pathlib import Path
import sqlite3

import pytest

from forgemind.schema.actions import AcceptedRunCommandToolAction
from forgemind.schema.permissions import (
    PendingRunCommandPermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.run_command import RunCommandArguments
from forgemind.state.permission_decision_registry import (
    DuplicatePermissionDecisionIdError,
    DuplicatePermissionRequestDecisionError,
    PermissionDecisionRequestMismatchError,
    UnknownPermissionRequestIdError,
)
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_permission_decision_registry import (
    CorruptStoredPermissionDecisionError,
    SQLitePermissionDecisionRegistry,
)
from forgemind.state.sqlite_permission_request_registry import (
    SQLitePermissionRequestRegistry,
)


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


def _request(
    action: AcceptedRunCommandToolAction,
    request_id: str = "permission-command-001",
) -> PendingRunCommandPermissionRequest:
    return PendingRunCommandPermissionRequest(
        permission_request_id=request_id,
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments,
        reason="命令需要用户确认",
        basis_ids=("policy-command-001",),
    )


def _decision(
    request: PendingRunCommandPermissionRequest,
    *,
    decision_id: str = "decision-command-001",
    value: PermissionDecision = PermissionDecision.APPROVE,
) -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        permission_decision_id=decision_id,
        permission_request_id=request.permission_request_id,
        task_id=request.task_id,
        action_id=request.action_id,
        decision=value,
        source="user",
        raw_response="同意" if value is PermissionDecision.APPROVE else "拒绝",
    )


def _registries(database_path: Path):
    actions = SQLiteActionRegistry(database_path)
    requests = SQLitePermissionRequestRegistry(database_path, actions)
    decisions = SQLitePermissionDecisionRegistry(database_path, requests)
    return actions, requests, decisions


def _persist_request(database_path: Path):
    actions, requests, decisions = _registries(database_path)
    action = _action()
    request = _request(action)
    actions.register(action)
    requests.register(request)
    return action, request, requests, decisions


def test_permission_decision_survives_registry_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    _, request, _, decisions = _persist_request(database_path)
    decision = _decision(request)
    decisions.record(decision)

    _, _, restarted = _registries(database_path)
    restored = restarted.get(decision.permission_decision_id)

    assert restored == decision
    assert restored is not decision
    assert restarted.get_for_request(request.permission_request_id) == decision


def test_permission_decision_requires_persisted_request(tmp_path: Path) -> None:
    _, _, decisions = _registries(tmp_path / "state.db")
    request = _request(_action())

    with pytest.raises(UnknownPermissionRequestIdError):
        decisions.record(_decision(request))


def test_permission_decision_must_match_request(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    _, request, _, decisions = _persist_request(database_path)
    mismatched = _decision(request).model_copy(
        update={"task_id": "other-task"}
    )

    with pytest.raises(PermissionDecisionRequestMismatchError):
        decisions.record(mismatched)


def test_duplicate_decision_id_does_not_overwrite(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    action, request, requests, decisions = _persist_request(database_path)
    original = _decision(request)
    decisions.record(original)
    second_request = _request(action, "permission-command-002")
    requests.register(second_request)

    with pytest.raises(DuplicatePermissionDecisionIdError):
        decisions.record(
            _decision(second_request, decision_id=original.permission_decision_id)
        )

    assert decisions.get(original.permission_decision_id) == original


def test_second_decision_for_same_request_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    _, request, _, decisions = _persist_request(database_path)
    original = _decision(request, value=PermissionDecision.APPROVE)
    decisions.record(original)

    with pytest.raises(DuplicatePermissionRequestDecisionError):
        decisions.record(
            _decision(
                request,
                decision_id="decision-command-002",
                value=PermissionDecision.REJECT,
            )
        )

    assert decisions.get_for_request(request.permission_request_id) == original


def test_corrupt_permission_decision_columns_are_rejected(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    _, request, _, decisions = _persist_request(database_path)
    decision = _decision(request)
    decisions.record(decision)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE permission_decisions
            SET decision = ?
            WHERE permission_decision_id = ?
            """,
            ("reject", decision.permission_decision_id),
        )

    with pytest.raises(CorruptStoredPermissionDecisionError):
        decisions.get(decision.permission_decision_id)
