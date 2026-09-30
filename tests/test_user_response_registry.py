import pytest

from forgemind.runtime.user_responses import UserResponseQuestionMismatchError
from forgemind.schema.actions import (
    AcceptedAskUserAction,
    AcceptedReadFileToolAction,
)
from forgemind.schema.interactions import UserResponseRecord, UserResponseType
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.user_response_registry import (
    DuplicateQuestionResponseError,
    DuplicateUserResponseIdError,
    InMemoryUserResponseRegistry,
    QuestionActionTypeError,
    UnknownQuestionActionIdError,
)


def make_question(
    *,
    action_id: str = "action-question-001",
) -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id=action_id,
        task_id="task-001",
        action_type="ask_user",
        reason="需要用户决定",
        question="请选择方案。",
        options=("A", "B"),
    )


def make_response(
    *,
    response_id: str = "response-001",
    question_action_id: str = "action-question-001",
    task_id: str = "task-001",
    selected_option: str = "A",
) -> UserResponseRecord:
    return UserResponseRecord(
        response_id=response_id,
        task_id=task_id,
        question_action_id=question_action_id,
        response_type=UserResponseType.ANSWER,
        raw_response=f"选 {selected_option}",
        selected_option=selected_option,
        cancellation_reason=None,
    )


def make_registry() -> InMemoryUserResponseRegistry:
    actions = InMemoryActionRegistry()
    actions.register(make_question())
    return InMemoryUserResponseRegistry(actions)


def test_registry_records_response_under_both_indexes() -> None:
    registry = make_registry()
    response = make_response()

    registry.record(response)

    assert registry.get("response-001") is response
    assert registry.get_for_question("action-question-001") is response


def test_registry_rejects_unknown_question_without_writing() -> None:
    registry = make_registry()
    response = make_response(question_action_id="action-question-999")

    with pytest.raises(UnknownQuestionActionIdError):
        registry.record(response)

    with pytest.raises(KeyError):
        registry.get(response.response_id)


def test_registry_rejects_tool_action_as_question() -> None:
    actions = InMemoryActionRegistry()
    actions.register(
        AcceptedReadFileToolAction(
            action_id="action-tool-001",
            task_id="task-001",
            action_type="tool_call",
            tool_name="read_file",
            arguments={"path": "src/app.py"},
            reason="读取代码",
        )
    )
    registry = InMemoryUserResponseRegistry(actions)

    with pytest.raises(QuestionActionTypeError):
        registry.record(make_response(question_action_id="action-tool-001"))


def test_registry_reuses_runtime_question_validation() -> None:
    registry = make_registry()

    with pytest.raises(UserResponseQuestionMismatchError):
        registry.record(make_response(task_id="task-other"))


def test_registry_rejects_duplicate_response_id_without_overwriting() -> None:
    actions = InMemoryActionRegistry()
    actions.register(make_question())
    actions.register(make_question(action_id="action-question-002"))
    registry = InMemoryUserResponseRegistry(actions)
    original = make_response()
    duplicate = make_response(
        question_action_id="action-question-002",
        selected_option="B",
    )

    registry.record(original)
    with pytest.raises(DuplicateUserResponseIdError):
        registry.record(duplicate)

    assert registry.get("response-001") is original


def test_registry_rejects_second_response_for_same_question() -> None:
    registry = make_registry()
    original = make_response()
    second = make_response(response_id="response-002", selected_option="B")

    registry.record(original)
    with pytest.raises(DuplicateQuestionResponseError):
        registry.record(second)

    assert registry.get_for_question("action-question-001") is original
    with pytest.raises(KeyError):
        registry.get("response-002")
