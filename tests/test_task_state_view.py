from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.schema.actions import (
    AcceptedReadFileToolAction,
)
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    RejectedObservation,
)
from forgemind.schema.permissions import (
    PendingReadFilePermissionRequest,
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.tasks import (
    ActionStateView,
    TaskRecord,
    TaskStateView,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _task(tmp_path: Path, task_id: str = "task-001") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        original_request="修复会员折扣没有生效的问题",
        project_root=str(tmp_path.resolve()),
    )


def _initial(task_id: str = "task-001") -> TaskStatusRecord:
    return TaskStatusRecord(
        task_status_id="status-001",
        task_id=task_id,
        revision=1,
        status=TaskStatus.RUNNING,
        reason="任务创建",
    )


def _action(
    action_id: str,
    task_id: str = "task-001",
) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id=task_id,
        action_type="tool_call",
        tool_name="read_file",
        arguments=ReadFileArguments(
            path=f"{action_id}.py",
            start_line=1,
            max_lines=20,
            expected_version="sha256:test-version",
        ),
        reason=f"读取 {action_id}",
    )


def _rejected(action_id: str) -> RejectedObservation:
    return RejectedObservation(
        action_id=action_id,
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户拒绝执行",
        ),
    )


def _permission_request(
    action: AcceptedReadFileToolAction,
) -> PendingReadFilePermissionRequest:
    return PendingReadFilePermissionRequest(
        permission_request_id=f"permission-{action.action_id}",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments,
        reason="读取范围需要用户确认",
        basis_ids=("policy-read-001",),
    )


def _permission_decision(
    request: PendingReadFilePermissionRequest,
) -> PermissionDecisionRecord:
    return PermissionDecisionRecord(
        permission_decision_id=f"decision-{request.action_id}",
        permission_request_id=request.permission_request_id,
        task_id=request.task_id,
        action_id=request.action_id,
        decision=PermissionDecision.REJECT,
        source="user",
        raw_response="拒绝",
    )


def test_task_state_view_rejects_status_from_another_task(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path, "task-001"),
            current_status=_initial("task-other"),
            actions=(),
        )


def test_task_state_view_rejects_action_from_another_task(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path, "task-001"),
            current_status=_initial("task-001"),
            actions=(
                ActionStateView(
                    sequence=1,
                    action=_action("action-001", "task-other"),
                    permission_request=None,
                    permission_decision=None,
                    observation=None,
                ),
            ),
        )


def test_task_state_view_rejects_non_continuous_action_sequence(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TaskStateView(
            task=_task(tmp_path),
            current_status=_initial(),
            actions=(
                ActionStateView(
                    sequence=2,
                    action=_action("action-002"),
                    permission_request=None,
                    permission_decision=None,
                    observation=None,
                ),
            ),
        )


def test_action_state_view_rejects_observation_for_another_action() -> None:
    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=_action("action-001"),
            permission_request=None,
            permission_decision=None,
            observation=_rejected("action-other"),
        )


def test_action_state_view_rejects_request_for_another_action() -> None:
    action = _action("action-001")
    other_request = _permission_request(_action("action-other"))

    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=action,
            permission_request=other_request,
            permission_decision=None,
            observation=None,
        )


def test_action_state_view_rejects_decision_without_request() -> None:
    action = _action("action-001")
    request = _permission_request(action)

    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=action,
            permission_request=None,
            permission_decision=_permission_decision(request),
            observation=None,
        )


def test_action_state_view_rejects_decision_for_another_request() -> None:
    action = _action("action-001")
    request = _permission_request(action)
    other_request = _permission_request(_action("action-other"))

    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=action,
            permission_request=request,
            permission_decision=_permission_decision(other_request),
            observation=None,
        )


def test_state_restores_task_current_view_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    first = SQLiteForgeMindState.open(database_path)
    task = _task(tmp_path)
    initial = _initial()
    first.create_task(task, initial)

    restored = SQLiteForgeMindState.open(database_path).get_task_view(
        task.task_id
    )

    assert restored == TaskStateView(
        task=task,
        current_status=initial,
        actions=(),
    )
    assert restored.task is not task
    assert restored.current_status is not initial


def test_state_view_requires_existing_task(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")

    with pytest.raises(KeyError):
        state.get_task_view("missing-task")


def test_state_view_restores_actions_in_registration_order(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    first = SQLiteForgeMindState.open(database_path)
    first.create_task(_task(tmp_path), _initial())
    first_action = _action("z-last-lexically")
    second_action = _action("a-first-lexically")
    first.actions.register(first_action)
    first.actions.register(second_action)
    second_request = _permission_request(second_action)
    first.permission_requests.register(second_request)
    second_decision = _permission_decision(second_request)
    first.permission_decisions.record(second_decision)
    second_observation = _rejected(second_action.action_id)
    first.observations.record(second_observation)

    restored = SQLiteForgeMindState.open(database_path).get_task_view(
        "task-001"
    )

    assert restored.actions == (
        ActionStateView(
            sequence=1,
            action=first_action,
            permission_request=None,
            permission_decision=None,
            observation=None,
        ),
        ActionStateView(
            sequence=2,
            action=second_action,
            permission_request=second_request,
            permission_decision=second_decision,
            observation=second_observation,
        ),
    )
