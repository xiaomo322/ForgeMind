"""验证模型输出说明与严格 AgentDecision 契约保持同步。"""

import json

from pydantic import TypeAdapter

from forgemind.context.messages import (
    AGENT_DECISION_SCHEMA_END,
    AGENT_DECISION_SCHEMA_START,
    build_agent_decision_output_contract,
)
from forgemind.schema.decisions import AgentDecision


def test_output_contract_contains_exact_agent_decision_schema() -> None:
    """协议中的 Schema 必须直接对应当前 AgentDecision。"""

    contract = build_agent_decision_output_contract()
    schema_text = contract.split(
        AGENT_DECISION_SCHEMA_START + "\n",
        maxsplit=1,
    )[1].split(
        "\n" + AGENT_DECISION_SCHEMA_END,
        maxsplit=1,
    )[0]

    assert json.loads(schema_text) == TypeAdapter(
        AgentDecision
    ).json_schema()


def test_output_contract_states_non_negotiable_output_rules() -> None:
    """模型必须知道格式边界和 action_id 的权威来源。"""

    contract = build_agent_decision_output_contract()

    assert "只返回一个" in contract
    assert "JSON" in contract
    assert "Markdown" in contract
    assert "action_id" in contract
    assert "Runtime" in contract
