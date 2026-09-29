import pytest
from pydantic import ValidationError

from forgemind.runtime.acceptance import accept_ask_user_decision
from forgemind.schema.actions import AcceptedAskUserAction
from forgemind.schema.decisions import AskUserDecision


def _decision() -> AskUserDecision:
    return AskUserDecision(
        action_type="ask_user",
        reason="项目中没有折扣叠加规则",
        question="会员折扣和优惠券可以同时使用吗？",
        options=("可以", "不可以"),
    )


def test_runtime_adds_authoritative_ids_to_ask_user_decision() -> None:
    decision = _decision()

    action = accept_ask_user_decision(
        decision,
        task_id="task-ask-001",
        next_action_id=lambda: "action-ask-001",
    )

    assert type(action) is AcceptedAskUserAction
    assert action.action_id == "action-ask-001"
    assert action.task_id == "task-ask-001"
    assert action.action_type == decision.action_type
    assert action.reason == decision.reason
    assert action.question == decision.question
    assert action.options == decision.options


def test_acceptance_uses_each_runtime_generated_action_id() -> None:
    generated_ids = iter(("action-ask-001", "action-ask-002"))

    first = accept_ask_user_decision(
        _decision(),
        task_id="task-ask-001",
        next_action_id=lambda: next(generated_ids),
    )
    second = accept_ask_user_decision(
        _decision(),
        task_id="task-ask-001",
        next_action_id=lambda: next(generated_ids),
    )

    assert first.action_id == "action-ask-001"
    assert second.action_id == "action-ask-002"


def test_acceptance_rejects_invalid_runtime_task_id() -> None:
    with pytest.raises(ValidationError):
        accept_ask_user_decision(
            _decision(),
            task_id="",
            next_action_id=lambda: "action-ask-001",
        )
