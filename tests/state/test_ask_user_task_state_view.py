from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.schema.actions import (
    AcceptedAskUserAction,
    AcceptedReadFileToolAction,
)
from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    RejectedObservation,
)
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.schema.permissions import PendingReadFilePermissionRequest
from forgemind.schema.tasks import (
    ActionStateView,
    TaskRecord,
    TaskStatus,
    TaskStatusRecord,
)
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _ask_action() -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id="action-ask-001",
        task_id="task-ask-001",
        action_type="ask_user",
        reason="项目中没有折扣叠加规则",
        question="会员折扣和优惠券可以同时使用吗？",
    )


def _tool_permission() -> PendingReadFilePermissionRequest:
    action = AcceptedReadFileToolAction(
        action_id="action-ask-001",
        task_id="task-ask-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/app.py",
            "expected_version": "sha256:v1",
        },
        reason="读取代码",
    )
    return PendingReadFilePermissionRequest(
        permission_request_id="permission-001",
        task_id=action.task_id,
        action_id=action.action_id,
        status="pending",
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments=action.arguments,
        reason="需要确认读取范围",
        basis_ids=("policy-001",),
    )


def _user_response(
    *,
    task_id: str = "task-ask-001",
    question_action_id: str = "action-ask-001",
) -> UserResponseRecord:
    return UserResponseRecord(
        response_id="response-001",
        task_id=task_id,
        question_action_id=question_action_id,
        response_type=UserResponseType.ANSWER,
        raw_response="可以叠加",
        selected_option=None,
        cancellation_reason=None,
    )


def test_ask_user_action_state_has_no_tool_execution_chain() -> None:
    view = ActionStateView(
        sequence=1,
        action=_ask_action(),
        user_response=None,
        permission_request=None,
        permission_decision=None,
        observation=None,
    )

    assert view.action.action_type == "ask_user"


def test_ask_user_action_state_accepts_its_user_response() -> None:
    view = ActionStateView(
        sequence=1,
        action=_ask_action(),
        user_response=_user_response(),
        permission_request=None,
        permission_decision=None,
        observation=None,
    )

    assert view.user_response == _user_response()


@pytest.mark.parametrize(
    "response",
    [
        _user_response(task_id="task-other"),
        _user_response(question_action_id="action-other"),
    ],
)
def test_ask_user_action_rejects_response_for_another_question(
    response: UserResponseRecord,
) -> None:
    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=_ask_action(),
            user_response=response,
            permission_request=None,
            permission_decision=None,
            observation=None,
        )


def test_ask_user_action_rejects_tool_permission_request() -> None:
    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=_ask_action(),
            user_response=None,
            permission_request=_tool_permission(),
            permission_decision=None,
            observation=None,
        )


def test_ask_user_action_rejects_tool_observation() -> None:
    with pytest.raises(ValidationError):
        ActionStateView(
            sequence=1,
            action=_ask_action(),
            user_response=None,
            permission_request=None,
            permission_decision=None,
            observation=RejectedObservation(
                action_id="action-ask-001",
                status="rejected",
                error=ObservationError(
                    code=ObservationErrorCode.PERMISSION_DENIED,
                    message="伪造的 Tool 结果",
                ),
            ),
        )


def test_sqlite_task_view_restores_ask_user_action(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    task = TaskRecord(
        task_id="task-ask-001",
        original_request="修复折扣规则",
        project_root=str(tmp_path.resolve()),
    )
    initial = TaskStatusRecord(
        task_status_id="status-ask-001",
        task_id=task.task_id,
        revision=1,
        status=TaskStatus.RUNNING,
        reason="任务创建",
    )
    state.create_task(task, initial)
    state.actions.register(_ask_action())

    restored = SQLiteForgeMindState.open(
        tmp_path / "state.db"
    ).get_task_view(task.task_id)

    assert restored.actions == (
        ActionStateView(
            sequence=1,
            action=_ask_action(),
            user_response=None,
            permission_request=None,
            permission_decision=None,
            observation=None,
        ),
    )
