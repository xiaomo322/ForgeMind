# ForgeMind End-to-End MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可创建任务、调用真实模型、执行五种 Tool、处理询问和权限、跨重启恢复并进入完成状态的 ForgeMind V0.1。

**Architecture:** SQLiteForgeMindState 继续作为权威事实源；应用服务组合单轮 Agent Loop 与确定性 handlers。受控 Tool 先写入权限请求，批准后进入 EXECUTING；edit_file 使用持久化前后版本计划对账文件系统副作用，其他执行保留真实终态。CLI 只负责参数和 JSON 输出，不包含业务规则。

**Tech Stack:** Python 3.11+、Pydantic 2.10、SQLite、OpenAI-compatible SDK、pytest、标准库 argparse/pathlib。

## Global Constraints

- 不修改或暂存用户独立的 `backend/forgemind/agent/loop.py`、FastAPI 学习文件及其依赖差异。
- 所有模型输出先通过现有严格 `AgentDecision` Parser。
- Tool 只能接收 Runtime 创建并持久化的 AcceptedAction。
- 用户批准只适用于一个不可变 `permission_request_id` 和对应参数快照。
- ForgeMind 完整回归排除 `tests/FastAPI学习` 与 `tests/test_fastapi.py`。
- 每个任务先观察测试失败，再实现、聚焦验证并原子提交。

---

### Task 1: EXECUTING 生命周期与 edit_file 执行计划

**Files:**
- Modify: `backend/forgemind/schema/tasks.py`
- Modify: `backend/forgemind/runtime/task_status.py`
- Create: `backend/forgemind/schema/execution.py`
- Create: `backend/forgemind/state/sqlite_edit_execution_plan_registry.py`
- Modify: `backend/forgemind/state/sqlite_state.py`
- Test: `tests/test_edit_execution_plan.py`
- Test: `tests/test_sqlite_edit_execution_plan_registry.py`
- Test: `tests/test_task_status.py`

**Interfaces:**
- Produces: `EditExecutionPlan`, `SQLiteEditExecutionPlanRegistry`, `TaskStatus.EXECUTING`.
- Produces: `record_permission_approval_executing(decision, plan, executing_status)`.

- [x] Add failing tests for strict plan fields, restart persistence, unique action plan, and `WAITING_USER -> EXECUTING -> RUNNING`.
- [x] Run focused tests and confirm missing enum/schema/registry failures.
- [x] Implement strict plan schema and SQLite registry with JSON/index cross-checks.
- [x] Wire the registry into `SQLiteForgeMindState.open()` and task views needed by recovery.
- [x] Implement atomic approval + plan + EXECUTING transaction with current-action validation.
- [x] Run focused tests and commit `feat: persist approved edit execution plans`.

### Task 2: edit_file 批准执行与崩溃恢复

**Files:**
- Create: `backend/forgemind/runtime/permission_approvals.py`
- Modify: `backend/forgemind/runtime/edit_file_execution.py`
- Modify: `backend/forgemind/state/sqlite_state.py`
- Test: `tests/test_edit_file_permission_approval.py`
- Test: `tests/test_edit_file_execution_recovery.py`

**Interfaces:**
- Produces: `approve_edit_file_permission(...) -> PermissionApprovalExecutionResult`.
- Produces: `resume_edit_execution(task_id, action_id, state) -> TerminalObservation`.

- [x] Test approval writes decision, plan and EXECUTING before file mutation.
- [x] Test current version equal to before version performs the edit once.
- [x] Test current version equal to after version reconstructs success without a second write.
- [x] Test any third version records VERSION_MISMATCH without overwriting user content.
- [x] Atomically save final Observation and RUNNING state after reconciliation.
- [x] Run focused and full ForgeMind tests; commit `feat: recover approved edit execution`.

### Task 3: run_tests 与 run_command 权限 handlers

**Files:**
- Modify: `backend/forgemind/runtime/permission_policy.py`
- Modify: `backend/forgemind/runtime/permissions.py`
- Create: `backend/forgemind/runtime/run_tests_handler.py`
- Create: `backend/forgemind/runtime/run_command_handler.py`
- Create: `backend/forgemind/runtime/permission_execution.py`
- Test: `tests/test_run_tests_agent_loop.py`
- Test: `tests/test_run_command_agent_loop.py`
- Test: `tests/test_permission_execution_handlers.py`

**Interfaces:**
- Produces handlers with the same Decision-only callable shape as existing Dispatcher handlers.
- Produces generic approve/reject entrypoints keyed by `permission_request_id`.

- [ ] Test both Decisions atomically enter WAITING_USER without executing subprocesses.
- [ ] Implement deterministic confirmation policies and pure pending request builders.
- [ ] Implement handlers using `record_tool_permission_waiting`.
- [ ] Test approval executes the persisted Action and records actual subprocess outcomes.
- [ ] Test rejection reuses the existing generic rejection path.
- [ ] Run focused/full tests; commit `feat: execute approved test and command actions`.

### Task 4: 显式完成 Decision 与统一 handlers

**Files:**
- Modify: `backend/forgemind/schema/decisions.py`
- Modify: `backend/forgemind/schema/actions.py`
- Modify: `backend/forgemind/runtime/acceptance.py`
- Modify: `backend/forgemind/runtime/decision_dispatch.py`
- Create: `backend/forgemind/runtime/completion.py`
- Create: `backend/forgemind/runtime/handlers.py`
- Modify: `backend/forgemind/state/sqlite_state.py`
- Test: `tests/test_completion_decision.py`
- Test: `tests/test_completion_runtime.py`
- Test: `tests/test_runtime_handlers.py`

**Interfaces:**
- Produces: `CompleteTaskDecision(action_type="complete", reason, summary)`.
- Produces: `complete_task(...)` that atomically saves AcceptedCompletionAction and COMPLETED.
- Produces: `build_runtime_handlers(task_id, state)`.

- [ ] Add strict parser/dispatch tests for complete while preserving six existing variants.
- [ ] Add AcceptedCompletionAction and SQLite serialization coverage.
- [ ] Implement atomic completion only from RUNNING and only when no latest Action lacks a terminal outcome or answer.
- [ ] Build handlers factory for ask/read/search/edit/tests/command/complete.
- [ ] Run focused/full tests; commit `feat: complete tasks through runtime decision`.

### Task 5: 多轮应用服务与 CLI

**Files:**
- Create: `backend/forgemind/application.py`
- Create: `backend/forgemind/cli.py`
- Modify: `pyproject.toml` using index-only staging for the ForgeMind script entry
- Test: `tests/test_application_service.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `ForgeMindApplication.create_task`, `run_until_pause`, `answer_question`, `decide_permission`, `get_task`.
- Produces: `forgemind` CLI with `start`, `run`, `status`, `answer`, `approve`, `reject` subcommands and JSON output.

- [ ] Test task creation persists absolute project root and RUNNING revision 1.
- [ ] Test run loop repeats immediate read/search results and stops on WAITING_USER, EXECUTING, COMPLETED, parse failure, or max steps.
- [ ] Test question answers and permission decisions resume the correct pending record.
- [ ] Load real model through existing config factory only in CLI composition root.
- [ ] Add CLI parser and stable JSON output; preserve API key secrecy.
- [ ] Run focused/full tests; commit `feat: add ForgeMind application and CLI`.

### Task 6: 真实端到端验收与文档

**Files:**
- Create: `tests/test_forgemind_end_to_end.py`
- Modify: `README.md`
- Modify: `docs/10-Agent执行循环.md`
- Modify: `docs/16-项目开发日志.md`

**Interfaces:**
- Consumes all previous public application service interfaces.
- Produces a documented runnable MVP workflow.

- [ ] Test fake-model sequence: search → read → edit wait → approve → run_tests wait → approve → complete.
- [ ] Close/reopen SQLite between permission wait and approval to prove restart recovery.
- [ ] Verify real files, observations, permission decisions and final COMPLETED state.
- [ ] Run `pytest` for all ForgeMind tests with the two independent FastAPI paths excluded.
- [ ] Run `git diff --check`, inspect final status, update docs and commit `docs: document end-to-end ForgeMind MVP`.
