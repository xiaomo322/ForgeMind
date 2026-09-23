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
| 05 | Tool 工具协议 | 初步确定 |
| 06 | 数据结构设计 | 实现中：Action、权限、Observation 与版本门禁 |
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
├── tools/    # 受控读取等具体操作
└── state/    # Action、Observation 与权限记录的内存注册表
tests/        # 与当前实现对应的行为测试
docs/         # 01–16 正式设计文档和开发日志
```

## 当前实现

- 严格、不可变的 Agent Decision 与 Runtime AcceptedAction；
- Runtime action_id 分配、Action 注册和重复编号保护；
- 权限检查三态、用户确认请求、用户决定及引用校验；
- rejected / failed Observation 及不可覆盖的终态登记；
- read_file 的安全路径解析、受限字节读取、首次版本建立、已有版本校验、按行分段和三类终态登记。
- search_code 的严格输入、匹配项和结果一致性 Schema，以及 Decision 到 Runtime AcceptedAction 的登记流程。

search_code、持久化 State 及完整 Agent Loop 尚未实现。

## 当前学习进度

当前学习 `06-数据结构设计`（更新于 2026-09-23）。read_file V0.1 已完成；search_code 已完成输入、结果、Decision、AcceptedAction 与 Action Registry 接入，下一步实现安全搜索范围解析。当前完整测试 143 项通过。详细设计演进见 `docs/06-数据结构设计.md`，逐步开发记录见 `docs/16-项目开发日志.md`。

每个切片只处理一个主要概念，并明确留出核心代码由用户先写；AI 提供脚手架、测试和基于真实错误的 Debug 支持。
