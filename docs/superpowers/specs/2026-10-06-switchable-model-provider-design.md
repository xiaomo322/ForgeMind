# 可切换单一模型厂商设计

日期：2026-10-06

## 目标

ForgeMind 每次运行只使用一个模型 API 厂商，但可以通过构造配置切换厂商、模型和可选 API 地址。Agent Loop、State、Decision Parser 和 Runtime 不感知具体厂商。

## 架构

保留现有 `AgentModel.generate(AgentTurnInput) -> str` 作为 ForgeMind 的稳定边界。新增 `LiteLLMAgentModel` 实现该协议，在内部使用 LiteLLM Python SDK 的统一 `completion()` 接口。

调用时只创建一个模型实例，例如使用 `openai/...`、`anthropic/...`、`gemini/...` 或 `ollama/...` 模型标识。切换厂商时替换模型配置和对应环境变量，不修改 Agent Loop。

第一版直接使用 LiteLLM Python SDK，不部署 LiteLLM Proxy，不实现多模型并行、自动路由、负载均衡或失败回退。

## 配置边界

模型实例包含：

- 非空 `model`：包含 LiteLLM 厂商前缀和模型名；
- 正数 `timeout_seconds`：限制一次模型调用等待时间；
- 可选 `api_base`：支持本地 Ollama 或 OpenAI 兼容服务地址；为 `None` 时不向 LiteLLM 传递该参数。

API Key 不写入配置对象、不写入日志、不写入 State，由 LiteLLM 按当前厂商从环境变量或厂商认证链读取。

## 数据流

1. `AgentTurnInput` 提供固定顺序的 system、user 消息。
2. 适配器把每条严格消息转换为 `{"role": ..., "content": ...}` 字典。
3. 调用注入的 `completion(model=..., messages=..., timeout=..., api_base=...)`。
4. 从统一响应的 `choices[0].message.content` 取得原始文本。
5. 只有非空字符串可以返回给现有 Decision Parser；空内容或错误响应抛出明确异常。

## 测试与错误

单元测试注入假的 `completion` 函数，不联网、不使用 API Key、不产生费用。测试核对模型参数、消息顺序、可选地址和原始文本返回。

LiteLLM 的认证、限流、网络及供应商错误保持原异常向上传递，供 `run_agent_turn()` 区分“模型调用失败”和“模型返回内容无法解析”。空响应由适配器转换为 ForgeMind 的 `EmptyModelResponseError`。

完成单元测试后，再由用户选择并配置一个实际厂商进行首次真实调用。首次真实调用只打印请求阶段、模型原始响应和解析结果，不执行 Tool 副作用。
