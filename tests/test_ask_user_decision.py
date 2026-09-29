import pytest
from pydantic import ValidationError

from forgemind.schema.decisions import AskUserDecision


def test_ask_user_decision_supports_free_text_question() -> None:
    decision = AskUserDecision(
        action_type="ask_user",
        reason="项目中没有折扣叠加规则",
        question="会员折扣和优惠券可以同时使用吗？",
    )

    assert decision.action_type == "ask_user"
    assert decision.options is None


def test_ask_user_decision_preserves_explicit_options() -> None:
    decision = AskUserDecision(
        action_type="ask_user",
        reason="需要用户选择处理方式",
        question="发现无效优惠券时应该怎样处理？",
        options=("返回原价", "拒绝订单"),
    )

    assert decision.options == ("返回原价", "拒绝订单")


@pytest.mark.parametrize(
    "invalid_field",
    [
        {"question": ""},
        {"reason": ""},
        {"options": ()},
        {"options": ("",)},
        {"tool_name": "read_file"},
        {"arguments": {"path": "src/app.py"}},
        {"action_id": "agent-must-not-create-this"},
    ],
)
def test_ask_user_decision_rejects_invalid_or_tool_only_fields(
    invalid_field: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "action_type": "ask_user",
        "reason": "缺少用户规则",
        "question": "折扣可以叠加吗？",
    }
    payload.update(invalid_field)

    with pytest.raises(ValidationError):
        AskUserDecision.model_validate(payload)
