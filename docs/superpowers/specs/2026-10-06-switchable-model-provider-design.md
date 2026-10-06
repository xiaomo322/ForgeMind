# 可切换单一模型厂商设计

日期：2026-10-06

## 目标

ForgeMind 每次运行只使用一个模型 API 厂商，并通过项目中的单一配置文件切换厂商地址、模型和调用参数。Agent Loop、State、Decision Parser 和 Runtime 不感知具体厂商。

## 架构

保留现有 `AgentModel.generate(AgentTurnInput) -> str` 作为稳定边界。第一版新增 `OpenAICompatibleAgentModel`，内部使用 OpenAI Python SDK 的 Chat Completions 接口。DeepSeek 支持该接口，因此可以先完成真实调用；其他兼容厂商只需替换配置。

第一版不引入 LiteLLM，不实现多模型并行、自动路由、负载均衡或失败回退。未来遇到不兼容 OpenAI 格式的厂商时，为同一个 `AgentModel` Protocol 增加新的适配器，不修改 Agent Loop。

## 单一配置文件

项目根目录新增 `config/model.toml`：

```toml
[model]
adapter = "openai_compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
```

字段含义：

- `adapter` 指定适配器类型，第一版只接受 `openai_compatible`；
- `base_url` 是当前 API 厂商地址；
- `model` 是厂商模型名；
- `api_key_env` 是保存密钥的环境变量名称；
- `timeout_seconds` 是单次请求超时秒数。

真实 API Key 不写入 TOML、不写入日志、不写入 State，也不提交到 Git。配置加载器读取 `api_key_env` 后，再从进程环境取得密钥。配置文件可以安全提交，因为它只包含环境变量名称。

配置由 Python 标准库 `tomllib` 读取，再通过严格 Pydantic 模型校验。文件不存在、TOML 语法错误、字段缺失、额外字段、空字符串或非正数超时都必须明确失败，不能使用隐藏默认值继续运行。

## 数据流

1. 应用启动时读取并校验 `config/model.toml`。
2. 工厂根据 `adapter` 创建唯一的 `OpenAICompatibleAgentModel`。
3. 适配器把严格 system、user 消息转换为 OpenAI Chat Completions 消息。
4. 调用配置中的 `base_url`、`model` 和 `timeout_seconds`，并启用 `response_format={"type": "json_object"}`。
5. 从 `choices[0].message.content` 取得模型原始文本。
6. 只有非空字符串可以返回给现有 Decision Parser；空内容或错误响应抛出明确异常。

## 测试与错误

配置测试使用临时 TOML 和临时环境变量，不读取开发者真实密钥。适配器测试注入假的客户端，不联网、不产生费用，并核对模型参数、消息顺序、JSON 模式和原始文本返回。

SDK 的认证、限流、网络及厂商错误保持原异常向上传递，供 `run_agent_turn()` 区分“模型调用失败”和“模型返回内容无法解析”。空响应由适配器转换为 ForgeMind 的 `EmptyModelResponseError`。

完成配置与适配器单元测试后，再设置 `DEEPSEEK_API_KEY` 进行首次真实调用。首次真实调用只打印调用阶段、模型原始响应和解析结果，不执行 Tool 副作用。
