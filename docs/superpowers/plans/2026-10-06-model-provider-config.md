# Model Provider Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从单一 `config/model.toml` 读取严格模型配置，并用可替换的 OpenAI 兼容适配器调用 DeepSeek。

**Architecture:** Python `tomllib` 读取 TOML，Pydantic 严格模型验证配置。`OpenAICompatibleAgentModel` 实现现有 `AgentModel` Protocol，厂商差异由 `base_url`、`model` 和密钥环境变量隔离。

**Tech Stack:** Python 3.11+、Pydantic 2.10.3、OpenAI Python SDK、pytest 8.3.4

## Global Constraints

- `config/model.toml` 不保存真实 API Key，只保存环境变量名称。
- 第一版只支持 `adapter = "openai_compatible"`。
- 模型原始响应仍由现有 Decision Parser 严格校验。
- 单元测试不联网、不读取真实密钥、不产生 API 费用。

---

### Task 1: 严格读取单一模型配置文件

**Files:**
- Create: `config/model.toml`
- Create: `backend/forgemind/config/__init__.py`
- Create: `backend/forgemind/config/model.py`
- Create: `tests/test_model_provider_config.py`

**Interfaces:**
- Produces: `ModelProviderConfig`、`ModelConfigDocument`、`load_model_provider_config(path: Path) -> ModelProviderConfig`

- [x] 写测试，覆盖正确读取、缺少 `[model]`、额外字段、空字符串和非正数超时。
- [x] 运行测试，确认因模块不存在而先失败。
- [ ] 创建严格配置模型：

```python
class ModelProviderConfig(StrictContractModel):
    adapter: Literal["openai_compatible"]
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key_env: str = Field(
        min_length=1,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    timeout_seconds: int = Field(gt=0)


class ModelConfigDocument(StrictContractModel):
    model: ModelProviderConfig
```

- [x] 由学习者完成 `load_model_provider_config()` 的三步核心逻辑：二进制打开、`tomllib.load()`、严格验证并返回 `.model`。
- [x] 运行配置测试并确认通过。

---

### Task 2: OpenAI 兼容 AgentModel 适配器

**Files:**
- Create: `backend/forgemind/agent/openai_compatible_model.py`
- Create: `tests/test_openai_compatible_model.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: `AgentTurnInput`、`ModelProviderConfig`
- Produces: `OpenAICompatibleAgentModel.generate()`、`create_openai_compatible_agent_model()`、`EmptyModelResponseError`、`MissingModelApiKeyError`

- [x] 使用假客户端写失败测试，核对 system/user 顺序、模型名、JSON 模式和返回文本。
- [x] 写空内容与缺少环境变量测试。
- [ ] 实现适配器：

```python
messages = [
    {"role": message.role, "content": message.content}
    for message in turn_input.messages
]
response = self.client.chat.completions.create(
    model=self.model,
    messages=messages,
    response_format={"type": "json_object"},
)
content = response.choices[0].message.content
```

- [x] 非空字符串原样返回；`None`、空串或纯空白抛出 `EmptyModelResponseError`。
- [x] 工厂从 `config.api_key_env` 指定的环境变量读取密钥，并使用 `base_url` 与 `timeout_seconds` 构造 `OpenAI` 客户端。
- [x] 使用 `uv add openai` 写入依赖和锁文件。
- [x] 运行适配器聚焦测试和完整回归。

---

### Task 3: DeepSeek 首次真实调用入口

**Files:**
- Create: `backend/forgemind/agent/model_smoke.py`
- Modify: `README.md`
- Modify: `docs/06-数据结构设计.md`
- Modify: `docs/16-项目开发日志.md`

**Interfaces:**
- Consumes: `config/model.toml`、`DEEPSEEK_API_KEY`
- Produces: 只调用模型并打印原始响应与解析结果的安全 smoke test

- [x] 加载配置并创建一个最小 RUNNING 任务上下文。
- [x] 调用一次真实模型，打印调用阶段、原始响应和 Decision 解析结果。
- [x] 明确不分派 Decision、不登记 Action、不执行 Tool。
- [x] 未配置密钥时打印可操作错误，不回显密钥。
- [x] 运行单元测试；配置真实密钥后再运行联网 smoke test。
- [x] 只记录实际执行结果并提交。
