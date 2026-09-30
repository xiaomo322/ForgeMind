# ForgeMind Agent 执行循环

**版本：V0.1**  
**状态：核心已确定**

## 1. 循环流程

```text
用户需求
  ↓
Agent Thinking
  ↓
生成 Action
  ↓
Runtime 结构校验
  ↓
权限与安全检查
  ↓
Tool 执行
  ↓
Observation
  ↓
Runtime 更新 State
  ↓
Agent 读取 State 并继续思考
```

## 2. 循环规则

1. Agent 每轮根据当前 State 决定下一步；
2. Action 必须是结构化的；
3. Runtime 不补全缺失参数；
4. Tool 执行结果必须形成 Observation；
5. 客观执行事实由 Runtime 根据结果写入 State；
6. Agent 根据成功、失败或错误 Observation 重新决策；
7. 未满足完成标准时不得声明任务完成。

## 3. 结束条件

- 需求已满足，且验证证据充分；
- 用户取消任务；
- 无法继续且决定终止本次运行，并已说明阻塞原因；
- 达到预设执行步数上限，停止继续执行并报告原因（具体限制后续设计）。

## 4. 循环驱动与暂停恢复

Runtime 中的确定性循环控制逻辑驱动每轮执行，Agent 决定下一步请求。循环控制逻辑本身不承担业务推理。

需要用户确认时，保存任务上下文、待确认操作及原因并暂停，不执行待授权工具，也不反复调用 Agent。等待确认不表示任务完成或终止。

用户同意后，核对具体授权并重新检查当前执行条件；例如文件已被用户修改，原替换条件不再成立时，应返回变化情况供 Agent 重新评估，不直接执行旧方案。调整后的操作若超出原授权对象或范围，应重新确认。

用户拒绝时不执行该操作，记录结果并交给 Agent 评估；用户取消任务时结束本次运行。

## 5. 单轮 Agent 推理边界

完整循环由可重复调用的单轮推理组成。`run_agent_turn()` 每次从 State
读取一个 `TaskStateView`，只允许状态为 `RUNNING` 的任务继续；随后依次
构造有限的 `AgentTaskContext`、供应商无关的 `AgentTurnInput`、调用模型，
并把模型原文严格解析为 `AgentDecision` 或
`AgentDecisionParseFailure`。

State 与模型通过最小 `Protocol` 注入。单轮编排不依赖 SQLite 内部实现，
也不依赖具体模型 SDK。模型调用发生前会拦截 `WAITING_USER` 和终态，避免
在等待或结束后产生冲突决策。

本边界只负责“读取 → 构造输入 → 模型生成 → 协议解析”。合法 Decision
尚未在这里获得 `action_id`，也不会直接执行 Tool；下一层 Runtime 分派才
能接受并执行它。模型网络或认证异常保持为真实调用异常，格式不合法则形成
稳定 ParseFailure，二者不能混淆。

测试覆盖合法询问决策、非法模型输出、非 RUNNING 状态提前拦截以及模型调用
异常透传。新增 4 项，相关回归 20 项、完整回归 521 项通过。

## 6. Agent Decision 的确定性 Runtime 分派

`dispatch_agent_decision()` 接收已经通过严格解析的 `AgentDecision`，依据
具体 Pydantic 模型类型选择 ask_user 或五种 Tool 的唯一处理器。分派过程不再
解析自然语言或路由字符串，不补全参数，也不直接拥有各 Tool 的专属执行依赖。

六个必填处理器由泛型 `AgentDecisionHandlers[DispatchResult]` 表达。调用方
负责把每个处理器连接到对应 Runtime 流程；遗漏处理器会在构造边界暴露，避免
字典路由中的拼写错误或静默缺项。

`dispatch_agent_decision_result()` 额外接收
`AgentDecisionParseFailure`。解析失败时原样返回，任何处理器都不会调用，
因此不会分配 action_id、登记 Action、请求权限或执行 Tool。未知动态类型会
抛出 `UnsupportedAgentDecisionError`，不能落入默认工具。

共享的 `ToolCallDecision`、`AgentDecision` 和
`AgentDecisionParseFailure` 已移入 Schema 层，使 Agent Parser 与 Runtime
Dispatcher 共同依赖稳定契约，避免 Runtime 反向依赖 Agent 实现。新增 8 项
测试，相关回归 30 项、完整回归 529 项通过。

## 7. 单轮 Agent Loop Step

`run_agent_loop_step()` 将前两层组合为一次可调用步骤：先运行
`run_agent_turn()` 取得模型输入、原始输出和解析结果，再调用
`dispatch_agent_decision_result()`。它不复制 Context、解析或路由逻辑。

`AgentLoopStepResult` 同时保存 `turn_result` 与 `dispatch_result`。前者用于
回答模型看到了什么、返回了什么以及协议是否有效；后者用于回答 Runtime
实际做了什么。两层结果不能压缩成一个模糊状态，否则无法区分模型服务失败、
Decision 格式失败和 Runtime 处理失败。

模型调用期间不持有 SQLite 写事务。模型思考前读取的 State 是输入快照，
具体 Runtime handler 在产生副作用前必须重新检查当前任务状态、权限、目标和
文件版本。这样既避免长时间锁库，也防止使用已经过期的 Agent 决策。

首条真实端到端路径使用 SQLite State：RUNNING 任务进入 Agent Context，模型
返回 AskUserDecision，Dispatcher 调用 ask_user Runtime 入口，最终原子写入
AcceptedAskUserAction 与 revision 2 的 WAITING_USER。非法模型输出路径保持
revision 1 的 RUNNING 且没有 Action。新增 2 项，相关回归 20 项、完整回归
531 项通过。
