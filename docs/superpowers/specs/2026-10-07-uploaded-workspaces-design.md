# ForgeMind 浏览器上传工作区设计

## 目标

浏览器用户不填写服务器本地路径。前端上传一个或多个 Python 文件，后端把文件保存到隔离工作区并返回 `workspace_id`；前端再使用该 ID 创建 Agent 任务。

Runtime 现有的 `project_root` 语义保持不变。Web 层负责把公开的 `workspace_id` 解析成后端内部绝对目录，再调用 `ForgeMindApplication.create_task()`。CLI 继续直接使用本地路径。

## 用户流程

```text
选择一个或多个 .py 文件
        ↓
POST /workspaces
        ↓
后端校验并保存到隔离目录
        ↓
返回 workspace_id 和公开文件清单
        ↓
POST /tasks { original_request, workspace_id }
        ↓
后端解析内部 project_root 并创建任务
        ↓
前端连接 GET /tasks/{task_id}/events
```

上传只建立工作区，不调用模型、不创建任务。创建任务只引用已经成功落盘的工作区，不再次上传文件。

## API 契约

### 创建上传工作区

```http
POST /workspaces
Content-Type: multipart/form-data
```

表单字段：

```text
files: 一个或多个 .py 文件
```

成功返回 HTTP 201：

```json
{
  "workspace_id": "workspace_...",
  "files": [
    {
      "path": "calculator.py",
      "size_bytes": 824
    }
  ],
  "file_count": 1,
  "total_size_bytes": 824
}
```

响应不包含工作区在服务器上的绝对路径。

### 从上传工作区创建任务

```http
POST /tasks
Content-Type: application/json
```

```json
{
  "original_request": "检查价格计算错误并修复",
  "workspace_id": "workspace_..."
}
```

成功返回 HTTP 201：

```json
{
  "task_id": "task_...",
  "original_request": "检查价格计算错误并修复",
  "workspace_id": "workspace_...",
  "status": "running",
  "revision": 1
}
```

Web API 不再接收或返回 `project_root`。当前接口尚无正式前端使用者，因此直接收紧公开契约；内部 `TaskRecord.project_root` 和 CLI 接口保持不变。

## 后端组件

### UploadedWorkspaceStore

工作区存储组件只负责：

- 生成不可预测的 `workspace_id`；
- 在配置的工作区根目录下建立隔离目录；
- 安全保存上传文件；
- 依据 `workspace_id` 恢复内部绝对目录；
- 返回不含服务器路径的文件元数据。

第一版使用本地文件系统实现，正式应用默认根目录为 `.forgemind/workspaces`。FastAPI 应用工厂通过参数接收 Store，使测试可以使用临时目录，路由不直接依赖固定全局路径。

工作区目录本身提供持久身份：进程重启后，只要 `workspace_<uuid>` 目录仍存在，Store 就能恢复它。第一版不新增 SQLite workspace 表，也不实现孤立工作区自动清理。

### Application 和 Runtime

现有 `ForgeMindApplication.create_task(original_request, project_root)` 不修改。Web 路由先调用 Store 解析 `workspace_id`，得到后端内部 `Path`，再调用 Application。

Agent、Runtime 和 Tool 继续只依赖 `TaskRecord.project_root`，无需知道文件来自浏览器上传还是 CLI 本地目录。

## 文件与安全边界

第一版规则：

- 每次至少上传 1 个、最多 20 个文件；
- 只接受扩展名为 `.py` 的普通文件；
- 每个文件最多 1 MiB，总大小最多 5 MiB；
- 文件内容必须能按 UTF-8 解码；
- 文件名只允许单层名称，不允许 `/`、`\`、绝对路径、`.` 或 `..`；
- Windows 下按不区分大小写检查重名，例如 `App.py` 与 `app.py` 冲突；
- 不静默覆盖同名文件；
- 上传阶段不导入、不执行 Python 文件；
- API 响应和错误详情不泄露服务器绝对路径。

所有文件先写入工作区根目录内的临时目录。只有全部文件校验和写入成功后，才把临时目录重命名为最终工作区目录。任一文件失败时清理临时目录，不返回 `workspace_id`。

第一版不接受 ZIP。ZIP 需要额外处理解压路径穿越、压缩炸弹、目录层级和文件总数，放到上传基础流程稳定后的独立阶段。

## 错误语义

- `422`：没有文件、空白任务目标、非法文件名、非 UTF-8 内容；
- `413`：单文件、文件总大小或文件数量超过限制；
- `415`：上传了非 `.py` 文件；
- `409`：同一批次出现重名文件；
- `404`：创建任务时引用的 `workspace_id` 不存在；
- `201`：工作区或任务已经成功持久化。

错误发生在创建任务之前时，不产生 `TaskRecord`。上传错误不留下最终工作区目录。

## 测试策略

1. 使用 FastAPI `TestClient` 以真实 multipart 请求上传一个 Python 文件，检查 HTTP 201、公开响应和磁盘原始字节。
2. 上传多个文件，检查数量、总大小和隔离目录内容。
3. 分别验证路径穿越文件名、非 `.py`、非 UTF-8、重名、大小和数量限制；失败后没有最终工作区。
4. 使用返回的 `workspace_id` 调用 `POST /tasks`，检查内部 `TaskRecord.project_root` 指向对应工作区，但公开响应不包含绝对路径。
5. 未知 `workspace_id` 返回 404，并确认 SQLite 中没有任务。
6. 使用工作区创建任务后连接现有 SSE，证明上传文件能够被真实 Agent Tool 读取。

测试使用临时存储根目录和假模型，不依赖外部 API Key。完成该模块后运行完整回归。

## 当前范围外

- ZIP 和完整目录树上传；
- Git 仓库 URL 克隆；
- 二进制文件、图片和非 Python 源码；
- 多用户登录、工作区所有权和配额；
- 云对象存储；
- 孤立工作区的定时清理；
- 在线直接执行用户上传代码。

## 前端衔接

前端第一版只需要三个连续动作：选择 `.py` 文件、显示上传清单、输入任务目标并创建任务。取得 `task_id` 后进入 Agent 时间线页面，复用现有 SSE、用户回答和后续权限接口。
