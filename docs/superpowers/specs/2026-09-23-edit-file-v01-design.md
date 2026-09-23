# Edit File V0.1 Design

**日期：** 2026-09-23  
**状态：** 已确认，等待实现计划  
**目标：** 为 ForgeMind 增加一个必须绑定已读取版本、获得独立用户授权、只执行一次精确替换并留下完整事实证据的 `edit_file` 闭环。

## 1. 范围

V0.1 只修改项目根目录内一个已经存在的 UTF-8 文本文件。调用者必须提供明确的旧文本、新文本和先前读取获得的 SHA-256 内容版本。旧文本必须在当前文件中恰好匹配一次。

V0.1 不创建文件，不支持正则、模糊匹配、忽略大小写、全部替换、多文件事务或任意大小文件。单个文件继续使用 64 KiB 硬上限。

## 2. 数据契约

`EditFileArguments` 包含：

- `path: str`：非空项目相对路径；
- `old_text: str`：非空精确匹配文本；
- `new_text: str`：替换内容，可以为空字符串以表达明确删除；
- `expected_version: str`：非空 SHA-256 版本标识，必须来自先前读取证据。

`old_text == new_text` 表示没有内容变化，由 Runtime 在调用 Tool 前拒绝，错误码为 `NO_CHANGE_REQUEST`。

`EditFileResult` 包含：

- `path`；
- `before_version`；
- `after_version`；
- `replacement_count`，V0.1 固定为 1；
- `diff`，由实际修改前后文本生成 unified diff。

成功结果必须满足：`before_version == expected_version`、前后版本不同、替换数量为 1、diff 非空。请求中的预览不能冒充实际结果。

## 3. Action 与权限

Agent 产生 `EditFileToolCallDecision`，其中不包含 `action_id`。Runtime 接受并校验后生成 `AcceptedEditFileToolAction`，分配唯一 `action_id` 并登记到 Action Registry。

每一个具体 edit_file Action 都必须创建独立的 `PendingEditFilePermissionRequest`。请求保存完整的 path、old_text、new_text、expected_version 参数快照。read_file 权限不能自动扩大为 edit_file 权限；任一参数或版本变化都需要新 Action 和新确认。

用户决定通过 permission_request_id 与 action_id 关联。批准后 Runtime 必须从 State 取回原来的不可变 AcceptedAction，再继续路径、版本和执行检查。拒绝形成 `rejected` Observation。

## 4. 执行顺序

```text
Agent Decision
→ Runtime 生成并登记 AcceptedAction
→ 创建并登记专属权限请求
→ 用户批准并取回原 Action
→ Runtime 检查项目安全路径和无变化请求
→ Tool 受限读取真实文件字节
→ 验证 UTF-8 和 expected_version
→ 检查 old_text 精确匹配数量
→ 在内存构造完整新文本和 unified diff
→ 在目标同目录写入完整临时文件
→ 复制原文件权限并同步临时文件内容
→ 再次读取目标并比较 expected_version
→ os.replace 原子切换目标路径
→ 根据实际写入字节计算 after_version
→ Runtime 登记唯一 success Observation
```

匹配为 0 或大于 1 时不写入。临时文件必须位于目标文件同目录，使 `os.replace` 不跨文件系统。任何替换前失败都要清理本次临时文件。

## 5. 状态与错误

Tool 调用前的权限拒绝、项目外路径和无变化请求记录为 `rejected`。Tool 已调用后的文件不存在、目录目标、文件超限、无效 UTF-8、版本冲突、零匹配、多匹配、临时文件写入失败或替换失败记录为 `failed`。

稳定错误码包括：

- `PERMISSION_DENIED`；
- `PATH_OUTSIDE_PROJECT`；
- `NO_CHANGE_REQUEST`；
- `FILE_NOT_FOUND`；
- `TARGET_IS_DIRECTORY`；
- `FILE_TOO_LARGE`；
- `INVALID_TEXT_ENCODING`；
- `VERSION_MISMATCH`；
- `EDIT_TARGET_NOT_FOUND`；
- `EDIT_TARGET_AMBIGUOUS`；
- `EDIT_WRITE_FAILED`。

只有目标文件实际切换到完整新内容，并生成一致的前后版本和 diff，才能记录 `success`。Observation 必须先登记到 State，再返回给 Agent；同一 Action 不能覆盖已有终态。

## 6. 原子性边界

V0.1 在内存构造全部新内容，再把完整字节写入同目录临时文件，调用 flush 和 fsync，并复制原目标文件的权限模式。替换前重新读取目标字节并验证版本，随后调用 `os.replace`。

该流程避免普通写入中途失败留下半文件，但不承诺断电后的目录项持久性、多文件事务或跨进程完全无竞争。版本复查与 `os.replace` 之间仍存在极短窗口；解决该窗口需要平台文件锁或更强事务机制，不属于 V0.1。

如果 `os.replace` 抛出异常，Runtime 只能确认操作未正常完成，不能仅凭异常断言目标文件绝对未变化。失败 Observation 保存安全错误类型；恢复流程应重新读取目标并比较 before/after 候选版本，不能盲目重试。

## 7. 模块边界

- `schema/edit_file.py`：Arguments、Result 和跨字段不变量；
- `schema/decisions.py`、`schema/actions.py`：Agent 决策与 Runtime 权威 Action；
- `schema/permissions.py`：edit_file 专属待确认请求；
- `runtime/acceptance.py`：接受和登记 Action；
- `runtime/permissions.py`：创建权限请求、解析用户决定和拒绝；
- `tools/edit_file.py`：匹配、候选内容、diff、临时文件与替换；
- `runtime/edit_file_execution.py`：路径检查、阶段错误映射、Tool 调用与 Observation 登记；
- `state/*_registry.py`：继续保持编号唯一、不可覆盖和来源可追溯。

## 8. 测试策略

测试分七个切片：

1. Arguments 与 Result 的严格类型和不变量；
2. Decision、AcceptedAction、Runtime 编号和重复编号保护；
3. edit_file 权限请求必须保存完整参数快照；
4. 唯一匹配、零匹配、多匹配、删除和真实 unified diff；
5. 临时文件成功替换、版本二次变化和写入失败清理；
6. success/rejected/failed Observation 与 State 唯一终态；
7. 学习者编写真实文件模块级测试，覆盖授权后的完整修改、版本变化、diff 和 State 对象身份。

每个实现切片先运行聚焦测试，再运行完整测试。完成模块后更新 README、数据结构设计和开发日志。
