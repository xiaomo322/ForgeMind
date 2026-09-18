# Permission Decision Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已登记的用户 `approve/reject` 决定转换成可追溯的权限检查结果，并让拒绝分支复用现有 rejected Observation 链路。

**Architecture:** Runtime 只按 `permission_decision_id` 从 State 读取权威决定。`approve` 转换为 `allowed` 并交给后续版本与安全检查；`reject` 转换为 `denied`，再由现有 `record_permission_rejection` 写入终态 Observation。

**Tech Stack:** Python 3.11+、Pydantic 2.10.3、pytest 8.3.4。

## Global Constraints

- 只处理已经登记到 `InMemoryPermissionDecisionRegistry` 的决定。
- 返回结果的 `basis_ids` 必须引用 `permission_decision_id`。
- `approve` 不调用 Tool，也不提前生成成功 Observation。
- `reject` 使用现有 `record_permission_rejection`，不复制拒绝记录逻辑。

---

### Task 1: Resolve a registered permission decision

**Files:**
- Create: `tests/test_permission_decision_resolution.py`
- Modify: `backend/forgemind/runtime/permissions.py`
- Modify: `README.md`
- Modify: `docs/06-数据结构设计.md`
- Modify: `docs/16-项目开发日志.md`

**Interfaces:**
- Consumes: `InMemoryPermissionDecisionRegistry.get(permission_decision_id)`
- Produces: `resolve_registered_permission_decision(permission_decision_id, *, decisions) -> PermissionCheckResult`

- [x] **Step 1: Write failing approve/reject resolution tests**
- [x] **Step 2: Run the focused test and confirm the missing interface failure**
- [x] **Step 3: Implement the minimal Runtime resolver**
- [x] **Step 4: Verify the focused tests and the complete rejection chain**
- [x] **Step 5: Update the learning summary and design log**
- [x] **Step 6: Run the full test suite and inspect the final diff**
