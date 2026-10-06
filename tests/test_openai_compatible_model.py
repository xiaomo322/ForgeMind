"""验证 OpenAI 兼容模型适配器的消息和响应边界。"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from forgemind.agent.openai_compatible_model import (
    EmptyModelResponseError,
    MissingModelApiKeyError,
    OpenAICompatibleAgentModel,
    create_openai_compatible_agent_model,
)
from forgemind.config.model import ModelProviderConfig
from forgemind.schema.context import AgentInputMessage, AgentTurnInput


@dataclass
class RecordingCompletions:
    """记录 SDK 参数，并返回可控制的假响应。"""

    content: str | None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content)
                )
            ]
        )


def _turn_input() -> AgentTurnInput:
    return AgentTurnInput(
        messages=(
            AgentInputMessage(role="system", content="只输出 JSON"),
            AgentInputMessage(role="user", content="检查折扣计算"),
        )
    )


def test_generate_sends_messages_and_returns_raw_content() -> None:
    completions = RecordingCompletions(
        '{"action_type":"ask_user","reason":"缺少规则",'
        '"question":"折扣能否叠加？"}'
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    model = OpenAICompatibleAgentModel(
        client=client,
        model="deepseek-v4-flash",
    )

    content = model.generate(_turn_input())

    assert content == completions.content
    assert completions.calls == [
        {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "只输出 JSON"},
                {"role": "user", "content": "检查折扣计算"},
            ],
            "response_format": {"type": "json_object"},
        }
    ]


@pytest.mark.parametrize("content", [None, "", "   "])
def test_generate_rejects_empty_model_content(
    content: str | None,
) -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=RecordingCompletions(content)
        )
    )
    model = OpenAICompatibleAgentModel(
        client=client,
        model="deepseek-v4-flash",
    )

    with pytest.raises(EmptyModelResponseError):
        model.generate(_turn_input())


def test_generate_preserves_real_client_failure() -> None:
    expected_error = ConnectionError("模型服务连接失败")

    class FailingCompletions:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            raise expected_error

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingCompletions())
    )
    model = OpenAICompatibleAgentModel(
        client=client,
        model="deepseek-v4-flash",
    )

    with pytest.raises(ConnectionError) as captured:
        model.generate(_turn_input())

    assert captured.value is expected_error


def _provider_config() -> ModelProviderConfig:
    return ModelProviderConfig(
        adapter="openai_compatible",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        timeout_seconds=60,
    )


def test_factory_builds_client_from_config_and_environment() -> None:
    calls: list[dict[str, Any]] = []
    expected_client = SimpleNamespace(chat=SimpleNamespace())

    def client_factory(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return expected_client

    agent_model = create_openai_compatible_agent_model(
        _provider_config(),
        environment={"DEEPSEEK_API_KEY": "secret-for-test"},
        client_factory=client_factory,
    )

    assert agent_model.client is expected_client
    assert agent_model.model == "deepseek-v4-flash"
    assert calls == [
        {
            "api_key": "secret-for-test",
            "base_url": "https://api.deepseek.com",
            "timeout": 60,
        }
    ]


@pytest.mark.parametrize(
    "environment",
    [{}, {"DEEPSEEK_API_KEY": ""}, {"DEEPSEEK_API_KEY": "   "}],
)
def test_factory_rejects_missing_or_blank_api_key(
    environment: dict[str, str],
) -> None:
    with pytest.raises(MissingModelApiKeyError) as captured:
        create_openai_compatible_agent_model(
            _provider_config(),
            environment=environment,
            client_factory=lambda **kwargs: SimpleNamespace(),
        )

    assert captured.value.environment_variable == "DEEPSEEK_API_KEY"
    assert "DEEPSEEK_API_KEY" in str(captured.value)
