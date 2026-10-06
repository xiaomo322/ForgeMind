"""调用兼容 OpenAI Chat Completions 协议的模型服务。"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from forgemind.config.model import ModelProviderConfig
from forgemind.schema.context import AgentTurnInput


class ChatCompletions(Protocol):
    """只声明 ForgeMind 实际使用的 SDK 调用能力。"""

    def create(self, **kwargs: Any) -> Any:
        """发送一次聊天补全请求。"""


class ChatResource(Protocol):
    """描述 client.chat 下需要存在的 completions 资源。"""

    completions: ChatCompletions


class OpenAICompatibleClient(Protocol):
    """描述适配器所需的最小客户端结构。"""

    chat: ChatResource


class EmptyModelResponseError(RuntimeError):
    """模型调用成功返回，但没有提供可用文本。"""


class MissingModelApiKeyError(RuntimeError):
    """配置指定的环境变量中没有可用的模型 API Key。"""

    def __init__(self, environment_variable: str) -> None:
        self.environment_variable = environment_variable
        super().__init__(
            f"环境变量 {environment_variable!r} 中没有可用的模型 API Key"
        )


@dataclass(frozen=True, slots=True)
class OpenAICompatibleAgentModel:
    """把供应商无关的 Agent 输入转换成兼容接口调用。"""

    client: OpenAICompatibleClient
    model: str

    def generate(self, turn_input: AgentTurnInput) -> str:
        """调用一次模型，并返回未经解析的原始文本。"""

        # 第一步：遍历 turn_input.messages，把每个 Pydantic 消息对象转换成
        # SDK 接受的 {"role": ..., "content": ...} 字典。
        messages = [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in turn_input.messages
        ]

        # 第二步：调用 self.client.chat.completions.create(...)。
        # 传入 self.model、第一步的 messages，并要求返回 JSON object。
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )

        # 第三步：从 response.choices[0].message.content 取得模型文本。
        content = response.choices[0].message.content

        # 第四步：如果 content 不是字符串，或者去掉空白后为空，抛出
        # EmptyModelResponseError("模型返回了空内容")。
        if not isinstance(content, str) or not content.strip():
            raise EmptyModelResponseError("模型返回了空内容")

        # 第五步：返回原始 content。这里不要解析 JSON，也不要 strip，
        # 后续 decision_parser 才负责协议校验，并保留真实模型原文作为证据。
        return content


def create_openai_compatible_agent_model(
    config: ModelProviderConfig,
    *,
    environment: Mapping[str, str] | None = None,
    client_factory: Callable[..., OpenAICompatibleClient] | None = None,
) -> OpenAICompatibleAgentModel:
    """根据严格配置和环境变量创建可调用的 AgentModel。"""

    # 第一步：environment 未传入时使用 os.environ；测试可以传入普通字典，
    # 从而不依赖开发电脑上的真实环境变量。
    selected_environment = (
        os.environ if environment is None else environment
    )

    # 第二步：使用 config.api_key_env 作为键读取 API Key。如果不存在、
    # 不是字符串或者去掉空白后为空，抛出 MissingModelApiKeyError。
    api_key = selected_environment.get(config.api_key_env)
    if not isinstance(api_key, str) or not api_key.strip():
        raise MissingModelApiKeyError(config.api_key_env)

    # 第三步：client_factory 未传入时，在这里导入 openai.OpenAI 并把它
    # 作为真正的客户端工厂。局部导入让假客户端单元测试无需联网。
    if client_factory is None:
        from openai import OpenAI

        client_factory = OpenAI

    # 第四步：调用客户端工厂，传入 api_key、config.base_url 和
    # config.timeout_seconds，得到 client。
    client = client_factory(
        api_key=api_key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
    )

    # 第五步：返回 OpenAICompatibleAgentModel(client=client,
    # model=config.model)。
    return OpenAICompatibleAgentModel(
        client=client,
        model=config.model,
    )
