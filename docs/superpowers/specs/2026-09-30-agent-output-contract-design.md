# Agent 输出协议设计

日期：2026-09-30

## 目标

让供应商无关的 `AgentTurnInput` 明确告诉大模型应返回什么，同时继续把模型输出视为不可信文本。模型输出只有通过现有 Pydantic 严格解析并由 Runtime 接受后，才能成为权威 Action。

## 设计

采用“简短行为规则 + 自动生成 JSON Schema”的组合：

1. 从现有 `AgentDecision` 联合类型生成 JSON Schema，避免 Prompt 与 Python 契约分别维护后发生字段漂移。
2. 在 system 消息中明确要求只输出一个 JSON 对象，不添加 Markdown 代码块或解释文字。
3. 明确禁止模型生成 `action_id`；它仍由 Runtime 在接受 Decision 时分配。
4. 模型只能选择 Schema 中已有的 `ask_user` 或五种 Tool Decision，不得创造近似工具名或额外字段。
5. 任务 Context 继续放在 user 消息中；输出协议和安全规则放在 system 消息中，避免项目文件内容改变协议。

## 模块边界

- `schema.decisions` 是字段、类型和联合分派的唯一事实来源。
- `context.messages` 负责把固定行为规则和生成的 Schema 写入 system 消息。
- `agent.turn` 继续只负责 State → Context → Model → Parser，不加入供应商逻辑。
- 后续真实模型适配器只转换消息并发起调用，不写 State、不生成 Action ID、不执行 Tool。
- `decision_parser` 继续对模型原始字符串做最终严格校验；Prompt 不能代替 Runtime 校验。

## 错误处理

模型返回非 JSON、Markdown 包裹、缺少字段、额外字段或错误类型时，现有 Parser 返回 `AgentDecisionParseFailure`。这类失败不产生 Action、不修改 State，也不调用 Tool。网络和认证错误仍由模型适配器作为真实调用异常抛出。

## 验证

测试应确认：

- system 消息包含单一 JSON、禁止 Markdown 和禁止 `action_id` 的规则；
- 输出协议来自 `AgentDecision` Schema，并覆盖 `ask_user` 与五个现有 Tool 名称；
- 任务 Context 仍单独位于 user 消息中；
- 现有合法 Decision 仍可解析，非法模型输出仍保持 State 不变。

## 本切片范围

本切片只建立供应商无关的输出协议。真实模型 SDK、API Key、重试、流式输出和 Tool Runtime handlers 留在后续独立切片中。
