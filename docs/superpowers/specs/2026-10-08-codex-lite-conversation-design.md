# ForgeMind 简化版 Codex 对话与附件设计

日期：2026-10-08  
状态：已确认界面方向，等待设计文档复核

## 1. 要解决的问题

当前 Web 工作台已经能上传一批 Python 文件、创建任务、通过 SSE 查看 Agent 执行、回答问题和处理权限，但它仍然更像一次性执行面板：

- 文件只能在创建 Workspace 时上传，任务开始后不能追加；
- 页面没有持续输入框，用户不能在同一任务中补充新要求；
- `TaskRecord.original_request` 只保存最初目标，不能表达后续消息；
- 文件已经保存在 Workspace 中，但任务页面没有持续可见的文件清单；
- Action、权限和结果分布在工作台区域，没有形成接近 Codex 的对话主线。

本次目标是把现有能力组织成“简化版 Codex”：用户以对话方式持续提出要求，工具执行、权限请求和验证结果作为可展开卡片嵌入对话；附件可以随消息上传，并在项目文件抽屉中恢复和查看。

## 2. 已确认的产品选择

采用“对话附件 + 项目文件抽屉”方案：

1. 页面主体是一条单列对话，不建立复杂的左右工作台。
2. 顶部只保留任务标题、当前状态和“项目文件”入口。
3. 底部输入框始终存在，左侧 `＋` 用于选择文件，也支持拖放。
4. 发送前，附件显示为可移除的“等待发送”文件片。
5. 发送后，附件保留在对应用户消息中，形成可审计记录。
6. 项目文件抽屉展示 Workspace 当前文件名、相对路径、大小和保存状态。
7. Agent 的 Tool 调用、权限、问题、Observation 和完成结果显示为对话中的过程卡片。
8. 页面只显示可审计的 Decision reason、Action 和真实执行结果，不展示模型服务没有提供的隐藏思维链。

第一版继续聚焦单个可信用户或受控内网，不增加账户、多人协作或任务侧栏。

## 3. 核心交互

### 3.1 创建任务

新任务页面仍先选择 1–20 个 UTF-8 `.py` 文件并填写目标。视觉上把现有 `WorkspaceForm` 改成居中的对话输入框，但调用顺序保持：

```text
选择文件和输入目标
  → POST /workspaces
  → POST /tasks
  → 打开 /?task=<task_id>
  → GET /tasks/{task_id}/events
```

只有 Workspace 创建和 Task 创建都成功后，页面才显示第一条已发送的用户消息。

### 3.2 在现有任务中发送消息和附件

用户可以只发送文字，也可以发送文字加附件。只有附件而没有文字时也允许发送，Agent Context 会明确描述“用户新增了以下文件”，但不会自动把文件内容塞入模型上下文；Agent 仍须通过 `read_file` 获取真实内容。

前端按两个请求完成一次带附件的发送。第一个请求只把文件保存到隔离的暂存区，不能让正在执行的 Tool 立即看到它：

```text
选中的附件
  → POST /tasks/{task_id}/files
  → 得到 upload_id、目标相对路径、大小和 sha256
  → POST /tasks/{task_id}/messages，引用这些 upload_id
  → 显示用户消息及 queued/applied 状态
```

暂存文件不会进入活动 Workspace，因此当前 `search_code`、`run_tests` 或 `run_command` 的文件视图不会在执行中途改变。消息到达安全边界时，Runtime 才把暂存文件发布到 Workspace，并把消息标为 applied。

如果第二个请求失败，暂存文件也不会成为不可见数据：文件抽屉显示“已上传，等待随消息应用”，用户可以重试发送消息或删除暂存文件。

### 3.3 运行中的消息

用户已确认：Agent 运行时允许继续发送消息，但不强行中断当前 Agent/Tool 步骤。

安全边界定义为：`run_agent_loop_step()` 已经返回，并且本步 Action、权限请求或 Observation 已完整写入 State；下一次 `run_agent_turn()` 尚未开始。

```text
当前 Agent/Tool 步骤运行中
  → 用户消息写入 SQLite，当前显示 queued
  → 附件保留在隔离暂存区，当前 Tool 看不到
  → 当前步骤继续，不改变其已接受参数
  → 步骤结果完整持久化
  → Runtime 在下一轮开始前领取 queued 消息并发布其附件
  → 消息追加 applied 事实
  → Context Builder 把它们放入下一轮模型输入
```

同一安全边界上存在多条消息时，按服务器分配的连续序号一起应用，不能依赖浏览器时间或随机 ID 排序。附件发布成功、消息 application 记录和必要的任务状态变化必须形成可恢复的执行计划；服务器崩溃后先对账附件哈希，再继续调用模型。

### 3.4 等待问题和权限

- 当任务正在等待 `ask_user` 回答时，底部输入框进入明确的“回答问题”模式；发送走现有 `/answers`，必须绑定 `question_action_id`。第一版回答模式不附加文件，回答完成后可以在普通消息模式上传。
- 当任务正在等待权限决定时，批准或拒绝仍必须点击对应权限卡片，普通文字不能被解释为授权。
- 权限等待期间可以上传文件或补充普通消息，但它们保持 queued；权限被处理、任务恢复 `RUNNING` 后，下一轮才会应用。

这可以防止“同意”“继续”等普通文本被错误地当成高风险操作授权。

### 3.5 完成后的继续对话

同一 `task_id` 支持完成后继续提出要求。已有 Completion Action 和 `COMPLETED` 状态不会删除或覆盖。此时没有正在运行的步骤，已经处于安全边界；新消息、附件发布结果、application 事实和新的 `RUNNING` 状态通过可恢复计划一起完成。

因此 `COMPLETED` 表示“上一轮目标已经完成”，而不是删除整段对话。只允许专用的“用户后续消息”入口执行 `COMPLETED → RUNNING`，普通 Runtime 状态接口仍不能随意重开终态。

`BLOCKED` 可以在用户提供新信息时通过同一专用入口恢复；`CANCELLED` 保持真正终态，用户需要创建新任务。

## 4. State 数据设计

### 4.1 不覆盖原始任务

`TaskRecord.original_request` 继续保持不可变，作为最初目标。后续消息使用独立记录：

```text
TaskMessageRecord
  message_id: str                 # Runtime 分配的权威 ID
  task_id: str
  sequence: int                   # 任务内从 1 开始连续递增
  content: str | None             # 保留用户原话
  attachment_upload_ids: tuple[str, ...]
```

`content` 和 `attachment_upload_ids` 至少有一项非空。每个 upload_id 必须属于同一任务，且尚未被其他消息使用。

暂存附件另有不可变记录：

```text
StagedWorkspaceFileRecord
  upload_id: str
  task_id: str
  requested_path: str
  size_bytes: int
  sha256: str
```

消息是否已经进入 Agent 上下文不通过覆盖字段表达，而是追加第二类事实：

```text
TaskMessageApplicationRecord
  message_application_id: str
  message_id: str
  task_id: str
  applied_after_action_sequence: int
```

没有 Application 记录表示 `queued`；存在记录表示 `applied`。`applied_after_action_sequence` 说明消息在哪条 Action 完成后的安全边界进入上下文，使刷新页面后仍能正确恢复对话顺序。

附件发布使用类似现有 `EditExecutionPlan` 的持久化计划。计划先记录预期 upload_id、目标相对路径和 sha256，再把同一存储分区中的暂存文件原子移动到活动 Workspace。若进程在移动后、登记 application 前退出，恢复逻辑会核对目标文件哈希：一致则补齐记录，不一致则停止并报告冲突，不能覆盖未知内容。

### 4.2 SQLite 规则

- `task_messages(task_id, sequence)` 建立唯一约束；序号在 `BEGIN IMMEDIATE` 事务内从当前最大值分配。
- 同一 `message_id` 最多有一条 application 记录。
- 同一 upload_id 最多被一条消息引用；活动文件和暂存文件共同保留文件名，避免发布时重名。
- 领取消息时一次读取当前全部 queued 消息，按 sequence 追加 application 记录。
- 有附件的消息先完成可恢复的发布计划，再登记 application；发布未完成时不能调用模型。
- 领取完成后才构造下一轮 Agent Context；模型调用期间不持有 SQLite 写锁。
- 纯文本消息的应用、完成任务重开和新 `RUNNING` 状态在一个 SQLite 事务中完成；文件系统副作用通过发布计划实现崩溃后对账。

`TaskStateView` 增加明确的消息视图，State 必须同时查询 Action 和消息，不能用字段缺失表示“没有检查”。

### 4.3 Agent Context

原始目标始终保留。Context 另外提供最近的已应用用户消息，并像 Action 历史一样显式报告：

- `total_message_count`
- `omitted_message_count`
- `is_message_history_complete`
- `recent_messages`

queued 消息不会进入当前模型输入。暂存附件也不会出现在 Tool 的 Workspace 中。附件发布完成后只向 Agent 提供相对路径、大小和 sha256，不自动提供文件正文。

## 5. Workspace 文件设计

### 5.1 保存和列出

复用现有 `FileSystemWorkspaceStore` 的受控根目录和文件限制。新增能力：

- 在活动 Workspace 之外暂存一批附件；
- 在安全边界把暂存文件发布到活动 Workspace；
- 列出活动文件和暂存文件；
- 返回相对路径、当前大小和 `sha256`；
- 从 Task 的内部 `project_root` 反向确认它确实属于当前 `workspace_store`。

公开 API 永远不返回服务器的绝对 `storage_root` 或 `project_root`。文件抽屉中的位置只显示 `/workspace/<relative-path>` 形式的公开相对位置。

第一版保持现有边界：只允许扁平 `.py` 文件、单文件不超过 1 MiB、单批总计不超过 5 MiB、Workspace 总文件数不超过 20。

新增文件与活动文件或其他暂存文件同名时返回 `409`，不能静默覆盖 Agent 已经读取、修改或等待应用的内容。显式替换文件和目录上传留给后续版本。

### 5.2 文件变化

文件抽屉每次打开或任务快照恢复时读取当前文件元数据，因此 Agent 通过 `edit_file` 修改后，大小和哈希反映磁盘当前事实。暂存文件显示“等待随消息应用”，活动文件显示“已保存”。消息附件保留发送时的文件名和上传哈希，不声称文件内容从未变化。

## 6. HTTP 接口

### 6.1 文件

```text
GET /tasks/{task_id}/files
  → { files: [{ path, size_bytes, sha256, state }], file_count, total_size_bytes }

POST /tasks/{task_id}/files
  Content-Type: multipart/form-data
  → { uploads: [{ upload_id, path, size_bytes, sha256, state: "staged" }] }

DELETE /tasks/{task_id}/files/staged/{upload_id}
  → 204，仅允许删除尚未被消息引用的暂存文件
```

上传端点继续受请求体中间件保护，在 Starlette 完整解析 multipart 前限制请求大小。

### 6.2 普通后续消息

```text
POST /tasks/{task_id}/messages
{
  "content": "同时检查折扣为 0 的情况",
  "attachment_upload_ids": ["upload_..."]
}

→ {
  "message_id": "message_...",
  "sequence": 2,
  "delivery": "queued" | "applied",
  "task_status": "running" | "waiting_user",
  "revision": 7
}
```

接口在写入前确认每个附件属于该任务 Workspace。未知路径、重复路径和跨 Workspace 引用均拒绝。

### 6.3 任务恢复

`GET /tasks/{task_id}` 在现有 Action 之外增加公开消息：

```text
messages: [
  {
    message_id,
    sequence,
    content,
    attachments: [{ path, size_bytes, sha256, state }],
    delivery,
    applied_after_action_sequence
  }
]
```

项目文件使用独立文件列表端点，避免把每次目录扫描塞进所有 Task 状态响应。消息响应包含它引用的稳定附件摘要，文件抽屉则返回 Workspace 当前状态。

## 7. 前端结构

主页面调整为以下组件：

```text
App
├── ConversationHeader          # 标题、状态、项目文件入口
├── ConversationTimeline        # 用户消息和 Agent 过程
│   ├── UserMessage
│   ├── AgentReason
│   ├── ToolActivityCard
│   ├── QuestionCard
│   ├── PermissionCard
│   └── CompletionCard
├── ProjectFilesDrawer          # 当前 Workspace 文件
└── MessageComposer             # 文本、附件、发送状态
```

时间线顺序由持久事实决定：原始目标在最前；已应用消息放在 `applied_after_action_sequence` 对应 Action 后；queued 消息显示在底部并带“已排队”标记。页面刷新后完全依靠 `GET /tasks/{task_id}` 恢复，不依赖 React 内存猜测。

Tool 卡片默认只显示 Tool 名、目标、状态和摘要；点击后展开 arguments 与公开 Observation。原始模型文本不默认展示。

文件抽屉在桌面端从右侧打开；窄屏使用全宽抽屉。每个文件显示名称、公开相对位置、大小和当前保存状态。第一版不提供在线代码编辑器。

## 8. 错误和恢复

- 上传失败：不发送消息，不创建假的聊天记录，显示服务器真实错误。
- 文件已暂存但消息发送失败：暂存文件保留在抽屉，输入内容和 upload_id 保留，可重试消息或删除暂存文件。
- 附件发布恢复发现哈希不一致：停止下一轮模型调用，保留计划和真实冲突证据。
- 消息已保存但 SSE 中断：刷新后仍能从 SQLite 看到 queued/applied 状态，显式重试连接。
- 重复文件名：返回 `409` 并说明已有文件保持不变。
- 任务正在等待权限：普通消息不能改变权限决定或提前执行 Tool。
- 同一任务多个页面发送消息：SQLite 连续序号决定权威顺序；现有 SSE 执行租约继续保证只有一条流驱动 Agent。
- Context 裁剪：必须显示省略数量，不能让 Agent 误认为看到了全部消息。

## 9. 安全边界

- 浏览器不能提交服务器绝对路径。
- 文件名继续拒绝 `/`、`\\`、绝对路径、`.` 和 `..`。
- upload_id 必须在 State 中恢复出同任务的暂存记录；目标路径仍须在 Workspace 内重新解析和核对。
- 上传限制在 HTTP 请求体、文件数量、单文件大小、总大小和编码五层执行。
- 文件内容、用户消息和 Tool 输出全部视为不可信 Context，不进入 system 规则。
- API Key 仍只保存在服务器环境变量中，文件抽屉和公开 Task 投影不得泄露。
- 本设计不扩大当前部署边界；公开多租户运行代码仍需要独立容器沙箱、认证和资源隔离。

## 10. 验证范围

### State 与 Runtime

- 消息序号连续、重复 ID 不覆盖、跨重启恢复；
- queued 消息在当前 Tool 完成前不进入模型输入，在下一安全边界进入；
- 多条 queued 消息按序一起应用；
- `COMPLETED` 和 `BLOCKED` 只有通过后续消息事务才能恢复 `RUNNING`；
- `CANCELLED` 拒绝后续消息；
- 权限等待期间消息不会形成隐式批准。

### Workspace 与 API

- 任务开始后可以追加新 `.py` 文件并列出；
- 重名、越界、超限、错误编码和跨 Workspace 附件引用被拒绝；
- 公开响应不出现真实服务器路径；
- 文件暂存成功而消息失败时，文件列表仍能恢复真实状态；
- 文件在当前 Tool 运行期间保持暂存，下一安全边界才出现在活动 Workspace；
- 发布中断后按 upload_id、目标路径和 sha256 对账恢复。

### 前端

- 选择、移除、上传附件的完整可见过程；
- 用户消息显示附件及 queued/applied；
- 项目文件抽屉可打开、刷新并在窄屏显示；
- 提问使用回答接口，权限只能通过权限卡片决定；
- 完成后发送消息能在同一任务继续；
- 刷新后恢复对话、文件和 Action 卡片。

### 端到端

用可控假模型运行：初始上传并创建任务 → Agent 开始 Tool → Tool 运行期间发送文字和附件 → 当前 Tool 的输入不变 → 下一轮模型看到补充消息 → Agent 修改并测试 → 完成 → 用户再次发消息 → 同一 task_id 恢复运行并再次完成。

测试必须打印并解释关键事实：消息写入时是 queued、哪条 Action 后变为 applied、下一轮模型实际收到什么，以及文件抽屉返回的相对路径和哈希。

## 11. 不在本次范围

- 文件夹、ZIP、二进制文件和超过当前限制的大项目上传；
- 在线代码编辑器、diff 编辑器和文件历史版本浏览；
- 同名文件的上传替换；
- 强制中断正在运行的模型调用或 Tool 进程；
- 多用户身份认证、跨用户 Workspace 分享；
- 跨进程 SSE 事件回放和通用消息广播；
- 完整 Codex 任务侧栏、Git 分支和终端界面。

这些能力不会阻塞本次“持续对话、对话附件、项目文件抽屉”的可用闭环。
