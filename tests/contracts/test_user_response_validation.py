import pytest

from forgemind.runtime.user_responses import (
    InvalidUserResponseSelectionError,
    UserResponseQuestionMismatchError,
    validate_user_response_for_question,
)
from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.interactions import UserResponseRecord, UserResponseType


def make_question(
    *,
    task_id: str = "task-001",
    action_id: str = "action-question-001",
    options: tuple[str, ...] | None = None,
) -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id=action_id,
        task_id=task_id,
        action_type="ask_user",
        reason="缺少用户决定",
        question="请确认使用哪种方案？",
        options=options,
    )


def make_response(
    *,
    task_id: str = "task-001",
    question_action_id: str = "action-question-001",
    response_type: UserResponseType = UserResponseType.ANSWER,
    selected_option: str | None = None,
) -> UserResponseRecord:
    return UserResponseRecord(
        response_id="response-001",
        task_id=task_id,
        question_action_id=question_action_id,
        response_type=response_type,
        raw_response="用户的原始回答",
        selected_option=selected_option,
        cancellation_reason=None,
    )


def test_matching_free_text_answer_is_returned_unchanged() -> None:
    response = make_response()

    result = validate_user_response_for_question(response, make_question())

    assert result is response


def test_matching_option_answer_is_returned_unchanged() -> None:
    response = make_response(selected_option="B")

    result = validate_user_response_for_question(
        response,
        make_question(options=("A", "B")),
    )

    assert result is response


@pytest.mark.parametrize(
    ("response", "expected_fields"),
    [
        (make_response(task_id="task-other"), ("task_id",)),
        (
            make_response(question_action_id="action-question-other"),
            ("question_action_id",),
        ),
        (
            make_response(
                task_id="task-other",
                question_action_id="action-question-other",
            ),
            ("task_id", "question_action_id"),
        ),
    ],
)
def test_mismatched_question_identity_is_rejected(
    response: UserResponseRecord,
    expected_fields: tuple[str, ...],
) -> None:
    with pytest.raises(UserResponseQuestionMismatchError) as exc_info:
        validate_user_response_for_question(response, make_question())

    assert exc_info.value.mismatched_fields == expected_fields


def test_free_text_question_rejects_selected_option() -> None:
    with pytest.raises(InvalidUserResponseSelectionError):
        validate_user_response_for_question(
            make_response(selected_option="B"),
            make_question(options=None),
        )


def test_option_question_requires_selected_option() -> None:
    with pytest.raises(InvalidUserResponseSelectionError):
        validate_user_response_for_question(
            make_response(selected_option=None),
            make_question(options=("A", "B")),
        )


def test_option_question_rejects_unknown_option() -> None:
    with pytest.raises(InvalidUserResponseSelectionError):
        validate_user_response_for_question(
            make_response(selected_option="C"),
            make_question(options=("A", "B")),
        )


def test_cancel_does_not_require_option_selection() -> None:
    response = make_response(response_type=UserResponseType.CANCEL)

    result = validate_user_response_for_question(
        response,
        make_question(options=("A", "B")),
    )

    assert result is response
