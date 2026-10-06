# ForgeMind

ForgeMind 是面向 Python / AI 应用开发者的项目级研发 Agent。V0.1 聚焦多文件 Python 项目的简单 Bug 修复闭环：理解需求、分析相关上下文、制定方案、按风险确认、修改代码、执行验证并报告结果。

## 当前原则

- Agent 负责思考、理解、规划、决策和判断；
- Tool 负责读取、修改和执行；
- 小决策自主继续，大决策交给用户确认；
- Runtime 在 Tool 执行前进行最终权限和安全拦截；
- 按任务需要获取上下文，不无差别读取整个项目；
- 安全优先于效率。

## 文档体系

| 编号 | 文档 | 状态 |
|---|---|---|
| 01 | 项目需求规格说明 | 已确认 |
| 02 | 产品设计 | 初步确定 |
| 03 | 系统总体架构 | 核心调用路径已确认 |
| 04 | Agent 架构设计 | 核心已确定 |
| 05 | Tool 工具协议 | read/search/edit 已实现 |
| 06 | 数据结构设计 | read/search/edit 闭环已实现 |
| 07 | RAG 设计 | MVP 后 |
| 08 | Memory 设计 | MVP 后 |
| 09 | Multi-Agent 设计 | MVP 后 |
| 10 | Agent 执行循环 | 核心已确定 |
| 11 | 安全设计 | 核心已确定 |
| 12 | Evaluation 评测方案 | 后续 |
| 13 | 测试方案 | 后续 |
| 14 | 部署方案 | 后续 |
| 15 | 开发规范 | 初步确定 |
| 16 | 项目开发日志 | 已建立 |

## 推进流程

```text
理解原理 → 用户实现核心代码 → AI 辅助补齐 → 测试与 Debug → 简短归档
```

教学重心采用“理解 30% → 用户实现 30% → AI 辅助 20% → 测试、Debug、解释 20%”。详细协作约定见项目根目录 `AGENTS.md`。

## 目录

```text
backend/forgemind/
├── agent/    # Agent 单轮推理、Decision 解析与模型供应商适配
├── config/   # TOML 应用配置的严格读取与校验
├── schema/   # 跨越 Agent、Runtime、Tool、State 边界的数据契约
├── runtime/  # Action 接受、权限、路径、版本和执行结果处理
├── tools/    # 受控读取、源码搜索和原子文件修改
└── state/    # Action、Observation 与权限记录的内存及 SQLite 注册表
tests/        # 与当前实现对应的行为测试
docs/         # 01–16 正式设计文档和开发日志
```

## 当前实现

- 严格、不可变的 Agent Decision 与 Runtime AcceptedAction；
- Runtime action_id 分配、Action 注册和重复编号保护；
- 权限检查三态、用户确认请求、用户决定及引用校验；
- rejected / failed Observation 及不可覆盖的终态登记；
- read_file 的安全路径解析、受限字节读取、首次版本建立、已有版本校验、按行分段和三类终态登记。
- search_code 的严格契约、Action 登记、安全范围解析、受限文本搜索和 success/rejected/failed 终态登记。
- edit_file 的版本绑定、逐 Action 用户确认、唯一精确替换、真实 diff、同目录临时文件和原子替换闭环。
- run_tests 的显式目标、逐 Action 权限、安全解析、真实 pytest、JUnit XML 及 Runtime/Observation 闭环。
- run_command V0.1 的严格契约、程序策略、Action 登记、逐 Action 授权、真实进程执行和完整证据链。
- SQLite 持久化 Action、权限请求、用户决定和 Observation，并已验证跨三次重启恢复完整执行链。
- `SQLiteForgeMindState.open()` 统一建立同一数据库上的五个 Registry，调用方不再手工连接依赖。
- 最小不可变 `TaskRecord` 保存 Runtime 任务编号、用户原始请求和绝对项目根目录。
- `SQLiteTaskRegistry` 以事务和主键持久化任务，并已接入统一 State 与跨重启流程。
- SQLite Action 登记要求 task_id 已存在，并由 Python 明确错误与数据库外键共同阻止孤立 Action。
- `TaskStatusRecord` 以 revision 表达追加式状态历史，Runtime 已实现合法生命周期转换检查。
- `SQLiteTaskStatusRegistry` 持久化连续状态历史，并已接入统一 State 和跨重启流程。
- `SQLiteForgeMindState.create_task()` 在一个事务中原子写入任务及初始 RUNNING 状态。
- Runtime 状态推进入口从当前权威记录分配下一 revision，登记成功后才返回新状态。
- `TaskStateView` 聚合任务来源、当前状态和有序 Action 历史；每条 Action 同时携带权限请求、用户决定及终态 Observation，尚不存在的阶段明确为 `None`。
- 权限请求以 Action 为唯一范围：同一 AcceptedAction 最多询问一次，并可按 action_id 严格恢复或明确返回 `None`。
- 第一版 Context Builder 按数量保留最近 Action，并显式提供总数、省略数和历史完整标记。
- Context Renderer 使用带 `schema_version` 和 `context_type` 的稳定 JSON Envelope，并保留中文原文。
- Agent 输入消息把固定系统规则与不可信 Context JSON 分别放入 `system`、`user` 角色，并强制顺序不变。
- Agent Decision Parser 依据 `tool_name` 把模型 JSON 严格分派为五种现有 Tool Decision，非法输出不能进入 Runtime。
- Agent 输出解析失败会复用稳定 Schema 问题列表反馈，不生成 Action 或虚构 Tool Observation。
- 完整 Agent Decision 已支持五种 Tool 调用和不携带 Tool 字段的 `ask_user`，并使用两层判别器严格路由。
- `config/model.toml` 集中保存模型厂商 URL、模型名、密钥环境变量名称与超时，真实 API Key 不进入项目文件。
- `OpenAICompatibleAgentModel` 已实现现有供应商无关 `AgentModel` 契约，严格传递 system/user 消息、JSON object 模式与模型原始文本。
- `forgemind-model-smoke` 已完成一次 DeepSeek 真实调用；合法 `search_code` 输出通过现有 Decision Parser，且冒烟入口不会登记或执行 Action。
- `search_code` 应用级 handler 已把模型 Decision、Runtime 权威编号、SQLite Action、受限 Tool 执行和 SQLite Observation 连接为单轮闭环，并在副作用前重新检查任务仍为 RUNNING。
- Runtime 可把 AskUserDecision 转换为带权威 task_id/action_id 的 AcceptedAskUserAction，尚未接入通用 Registry。
- 内存 Action Registry 已使用两层 AcceptedAction 联合，Tool 与 AskUserAction 共用不可覆盖的 ID 空间。
- 新建 SQLite Action Registry 已能保存和严格恢复 Tool/AskUserAction，并交叉核对通用索引列与完整 JSON。
- 旧版 Tool 专用 actions 表会在事务中迁移为通用结构，保留记录、任务序号和外部引用名称。
- TaskStateView 已支持 AskUserAction，并拒绝为询问 Action 拼接 Tool 权限记录或 Tool Observation。
- SQLiteForgeMindState 可在一个事务中登记 AskUserAction 与 WAITING_USER 状态，任一写入失败会整体回滚。
- 高层 ask_user Runtime 入口负责生成权威编号、构造下一状态并在提交成功后返回等待结果。
- State 为每个任务内的 Action 分配独立连续序号，恢复历史时按照登记顺序返回，不从随机 `action_id` 推断先后。

真实模型尚未接入应用级多轮 Loop；五种 Tool Decision 的 Runtime handlers 仍需统一组装。

## 当前学习进度

当前学习真实模型进入 Agent Loop 的边界（更新于 2026-10-06）。五个 Tool V0.1 均已形成完整证据链；`ask_user` 从 Agent Decision、WAITING_USER、持久化用户响应到后续状态的两条链路已完成。供应商无关的单轮 Agent 入口现已与确定性 Runtime 分派组合为可运行 Loop Step。模型 system 消息包含由严格 `AgentDecision` 自动生成的 JSON Schema，OpenAI 兼容适配器从 `config/model.toml` 和环境变量建立真实 DeepSeek 客户端。安全冒烟入口已取得真实 `search_code` JSON 并通过 Parser。`search_code` 现已进一步接入应用级 handler：假模型端到端测试证明 Decision 经 Runtime 分配 `action_id`、写入 SQLite、执行受限搜索并登记终态 Observation；任务状态在模型思考期间变化时不会登记旧 Decision。下一步按同一结构接入 `read_file`，再处理需要权限的 edit/test/command handler。ForgeMind 测试 553 项通过；另有 2 项未提交 FastAPI 学习测试因固定 task_id 期望与随机 UUID 实现不一致而失败。详细设计演进见 `docs/06-数据结构设计.md`，逐步开发记录见 `docs/16-项目开发日志.md`。

每个切片只处理一个主要概念，并明确留出核心代码由用户先写；AI 提供脚手架、测试和基于真实错误的 Debug 支持。
