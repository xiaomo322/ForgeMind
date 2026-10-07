# ForgeMind FastAPI SSE 流式输出设计

## 目标

为 ForgeMind 增加类似 Codex 执行时间线的流式输出，让客户端在任务运行期间逐条收到 Agent 决策、Tool 执行结果、等待用户和任务完成事件。

本功能采用渐进教学方式实现。每个阶段只引入一个主要概念，并通过真实测试观察 HTTP 响应。用户可以选择亲手完成核心代码，也可以让 AI 补齐后逐行讲解。

## 技术选择

第一版使用 FastAPI `StreamingResponse` 和 Server-Sent Events（SSE）。SSE 符合当前服务器向客户端单向推送任务进度的需要，协议简单，并能在后续加入事件编号和断线恢复。

用户批准、拒绝和回答问题仍使用独立的普通 POST 请求。第一版不使用 WebSocket。

## 数据流

```text
ForgeMindApplication
        │
        │ 每完成一轮 Agent Loop
        ▼
AgentLoopStepResult
        │
        │ 映射为公开事件
        ▼
StreamEvent
        │
        │ 编码为 SSE 文本
        ▼
StreamingResponse
        │
        ▼
客户端逐条接收
```

`yield` 只负责把下一块数据交给 `StreamingResponse`。`StreamingResponse` 负责通过同一个 HTTP 响应逐块发送数据。

## 实现阶段

### 阶段一：最小 SSE 实验

- 建立一个学习端点，连续产生三条固定事件。
- 学习生成器暂停与恢复、`StreamingResponse` 和 `text/event-stream`。
- 使用 FastAPI `TestClient.stream()` 读取真实响应。
- 不连接模型、SQLite 或 ForgeMind Runtime。

### 阶段二：统一事件契约

- 定义 `StreamEvent`，至少包含 `event`、`sequence`、`task_id` 和 `data`。
- 编写单一 SSE 编码函数，生成 `event:`、`id:`、`data:` 和结尾空行。
- 测试 JSON、中文和事件顺序。

### 阶段三：连接 ForgeMind Agent 步骤

- 将 `ForgeMindApplication.run_until_pause(..., on_step=...)` 的结果转换为公开事件。
- 每次只驱动有限步骤，及时产出事件。
- 输出 Agent 的公开 `reason`、Decision、Runtime 结果和任务状态。
- 不输出模型服务未提供的隐藏思维链。

### 阶段四：等待用户与恢复执行

- 流中发送 `task.waiting_user`。
- 使用独立 POST 端点提交问题回答或权限决定。
- 用户响应写入权威 State 后，可以重新连接事件流继续任务。

### 阶段五：模型文本增量

- 在模型适配器支持流式调用后增加 `model.output.delta`。
- 保留完成后的严格 JSON 解析，不能用未完成片段执行 Tool。
- 该阶段完成后才提供逐字生成效果。

## 第一版事件类型

```text
task.started
agent.step
task.waiting_user
task.completed
task.failed
```

后续按实际需要增加 Tool 和模型增量事件，不提前建立复杂事件总线。

## 错误处理

- 建立流之前无法找到任务：返回普通 HTTP 404。
- 流建立后的执行错误：发送 `task.failed` 事件，然后结束生成器。
- 模型输出解析失败：发送带结构化错误信息的失败事件，不伪造 Decision。
- 客户端断开：停止继续驱动 Agent，后续通过持久化 State 恢复。

## 测试策略

每个阶段使用两类测试：

1. 小型单元测试验证事件格式和字段。
2. FastAPI 流式测试验证状态码、`content-type`、事件顺序和响应内容。

连接真实 ForgeMind 后，测试使用可控的假模型，避免单元测试依赖 API Key 和外部网络。真实模型只用于手动端到端验证。

## 当前范围外

- WebSocket 双向长连接；
- 多服务器事件代理；
- Redis 消息队列；
- 完整网页界面；
- 生产级跨进程断线回放；
- 展示模型隐藏思维链。
