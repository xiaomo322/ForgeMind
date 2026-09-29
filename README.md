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
- State 为每个任务内的 Action 分配独立连续序号，恢复历史时按照登记顺序返回，不从随机 `action_id` 推断先后。

统一任务 State 及完整 Agent Loop 尚未实现。

## 当前学习进度

当前学习 Agent 推理边界（更新于 2026-09-29）。五个 Tool V0.1 均已形成完整证据链；Context Builder、JSON Renderer 和角色分离的消息构建已经完成。下一步把模型返回的 JSON 严格解析为现有 Tool Decision，错误输出必须停在解析边界，不能进入 Runtime 接受流程。当前完整测试 421 项通过。详细设计演进见 `docs/06-数据结构设计.md`，逐步开发记录见 `docs/16-项目开发日志.md`。

每个切片只处理一个主要概念，并明确留出核心代码由用户先写；AI 提供脚手架、测试和基于真实错误的 Debug 支持。
