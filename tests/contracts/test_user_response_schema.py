import pytest
from pydantic import ValidationError

from forgemind.schema.interactions import UserResponseRecord, UserResponseType


def test_free_text_answer_is_valid() -> None:
    response = UserResponseRecord(
        response_id="response-001",
        task_id="task-001",
        question_action_id="action-question-001",
        response_type=UserResponseType.ANSWER,
        raw_response="请使用 SQLite。",
        selected_option=None,
        cancellation_reason=None,
    )

    assert response.selected_option is None
    assert response.raw_response == "请使用 SQLite。"


def test_option_answer_is_valid() -> None:
    response = UserResponseRecord(
        response_id="response-002",
        task_id="task-001",
        question_action_id="action-question-001",
        response_type=UserResponseType.ANSWER,
        raw_response="选 B",
        selected_option="B",
        cancellation_reason=None,
    )

    assert response.selected_option == "B"


def test_cancel_without_normalized_reason_is_valid() -> None:
    response = UserResponseRecord(
        response_id="response-003",
        task_id="task-001",
        question_action_id="action-question-001",
        response_type=UserResponseType.CANCEL,
        raw_response="先停止这个任务。",
        selected_option=None,
        cancellation_reason=None,
    )

    assert response.response_type is UserResponseType.CANCEL


@pytest.mark.parametrize(
    "field_name",
    ["response_id", "task_id", "question_action_id", "raw_response"],
)
def test_required_text_fields_reject_empty_strings(field_name: str) -> None:
    values = {
        "response_id": "response-001",
        "task_id": "task-001",
        "question_action_id": "action-question-001",
        "response_type": UserResponseType.ANSWER,
        "raw_response": "使用 SQLite。",
        "selected_option": None,
        "cancellation_reason": None,
    }
    values[field_name] = ""

    with pytest.raises(ValidationError):
        UserResponseRecord.model_validate(values)


def test_answer_rejects_cancellation_reason() -> None:
    with pytest.raises(ValidationError):
        UserResponseRecord(
            response_id="response-001",
            task_id="task-001",
            question_action_id="action-question-001",
            response_type=UserResponseType.ANSWER,
            raw_response="使用 SQLite。",
            selected_option=None,
            cancellation_reason="不再继续",
        )


def test_cancel_rejects_selected_option() -> None:
    with pytest.raises(ValidationError):
        UserResponseRecord(
            response_id="response-001",
            task_id="task-001",
            question_action_id="action-question-001",
            response_type=UserResponseType.CANCEL,
            raw_response="停止任务。",
            selected_option="B",
            cancellation_reason=None,
        )


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UserResponseRecord.model_validate(
            {
                "response_id": "response-001",
                "task_id": "task-001",
                "question_action_id": "action-question-001",
                "response_type": "answer",
                "raw_response": "使用 SQLite。",
                "selected_option": None,
                "cancellation_reason": None,
                "agent_guess": "SQLite",
            }
        )
