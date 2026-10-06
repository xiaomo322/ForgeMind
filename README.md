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
- `read_file` 应用级 handler 已接入同一单轮闭环；分段结果的真实内容、版本与 `eof=false` 会持久化供下一轮 Agent 使用。
- `edit_file` 的确定性权限策略会为每个具体 Action 生成待确认快照；SQLite State 已能在一个事务中原子保存 Action、权限请求与 `WAITING_USER` 状态，冲突时三者整体回滚。
- `edit_file` 应用级 handler 已接入 Agent Loop；模型提出修改后只保存待确认事实并暂停，用户批准前不会修改文件或生成 Observation。
- 用户拒绝具体权限请求时，Runtime 会原子保存 `REJECT` 决定、rejected Observation 和下一版 `RUNNING`，文件保持不变，Agent 可依据拒绝事实评估其他方案。
- Runtime 可把 AskUserDecision 转换为带权威 task_id/action_id 的 AcceptedAskUserAction，尚未接入通用 Registry。
- 内存 Action Registry 已使用两层 AcceptedAction 联合，Tool 与 AskUserAction 共用不可覆盖的 ID 空间。
- 新建 SQLite Action Registry 已能保存和严格恢复 Tool/AskUserAction，并交叉核对通用索引列与完整 JSON。
- 旧版 Tool 专用 actions 表会在事务中迁移为通用结构，保留记录、任务序号和外部引用名称。
- TaskStateView 已支持 AskUserAction，并拒绝为询问 Action 拼接 Tool 权限记录或 Tool Observation。
- SQLiteForgeMindState 可在一个事务中登记 AskUserAction 与 WAITING_USER 状态，任一写入失败会整体回滚。
- 高层 ask_user Runtime 入口负责生成权威编号、构造下一状态并在提交成功后返回等待结果。
- State 为每个任务内的 Action 分配独立连续序号，恢复历史时按照登记顺序返回，不从随机 `action_id` 推断先后。

## 运行端到端 MVP

API Key 仍只放在环境变量中；变量名由 `config/model.toml` 的
`api_key_env` 指定。以当前 DeepSeek 配置为例：

```powershell
$env:DEEPSEEK_API_KEY = "你的 API Key"
```

创建任务并运行到需要用户输入或完成：

```powershell
uv run --no-sync python -m forgemind.cli start "修复项目中的折扣错误" --project-root .
```

CLI 会输出 JSON，其中包含 `task_id`、状态和本次执行步数。后续可以使用：

```powershell
python -m forgemind.cli status <task_id>
python -m forgemind.cli run <task_id>
python -m forgemind.cli answer <task_id> <question_action_id> "用户回答"
python -m forgemind.cli approve <task_id> <permission_request_id>
python -m forgemind.cli reject <task_id> <permission_request_id>
```

安装项目后也可以直接使用 `forgemind` 命令。SQLite 默认保存在
`.forgemind/state.db`，可通过全局 `--database` 参数指定其他位置。

### 从 Python 代码调用

真正的代码入口是 `ForgeMindApplication`，CLI 也只是调用这一层：

```python
from pathlib import Path

from forgemind.agent.openai_compatible_model import (
    create_openai_compatible_agent_model,
)
from forgemind.application import ForgeMindApplication
from forgemind.config.model import load_model_provider_config
from forgemind.state.sqlite_state import SQLiteForgeMindState

config = load_model_provider_config(Path("config/model.toml"))
model = create_openai_compatible_agent_model(config)
state = SQLiteForgeMindState.open(Path(".forgemind/state.db"))
app = ForgeMindApplication(state=state, model=model)

task = app.create_task("修复 add 函数并运行测试", Path("你的项目目录"))
result = app.run_until_pause(
    task.task_id,
    on_step=lambda number, step: print(step.turn_result.raw_response),
)
print(result.status)
```

包含用户询问和权限确认循环的完整示例位于
`examples/calculator_demo/run_agent.py`。示例会逐轮打印模型输入上下文、原始
JSON 回复、严格解析后的 Decision 和 Runtime 结果。模型服务内部未返回的隐藏
思维链不可读取；Decision 的 `reason` 是可记录、可审计的决策理由。

当前 MVP 已接通真实模型、多轮 Agent Loop、七种 Decision 路由、五种
Tool、用户询问、逐 Action 权限、SQLite 重启恢复、显式完成状态和 CLI。

## 当前学习进度

当前 ForgeMind V0.1 端到端 MVP 已完成（更新于 2026-10-06）。应用服务可以创建任务、连续调用真实模型、执行立即型 Tool、暂停等待问题或权限、恢复用户决定，并在证据完整时进入 `COMPLETED`。`edit_file` 使用持久化执行计划和 `EXECUTING` 状态跨进程对账；`run_tests` 与 `run_command` 保存真实进程结果。端到端测试覆盖 search → read → edit → approve → pytest → approve → complete，并在权限阶段重启 SQLite State。详细设计演进见 `docs/06-数据结构设计.md`，逐步开发记录见 `docs/16-项目开发日志.md`。

每个切片只处理一个主要概念，并明确留出核心代码由用户先写；AI 提供脚手架、测试和基于真实错误的 Debug 支持。
