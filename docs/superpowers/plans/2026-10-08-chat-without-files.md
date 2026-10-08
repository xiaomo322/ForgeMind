# Chat Without Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users start a persistent ForgeMind conversation without uploading project files.

**Architecture:** Keep the invariant that every task owns a server-managed workspace. When task creation omits `workspace_id`, FastAPI creates an empty workspace and passes its root into the unchanged Application/State task creation flow.

**Tech Stack:** Python, FastAPI, Pydantic v2, React, TypeScript, Vitest.

## Global Constraints

- Every task still has a managed workspace directory.
- Existing file and ZIP uploads remain compatible.
- An empty workspace can receive later message attachments.
- Browsers never submit or receive an absolute server path.

---

### Task 1: Empty workspace and optional task workspace

**Files:**
- Modify: `backend/forgemind/web/workspaces.py`
- Modify: `backend/forgemind/web/agent_api.py`
- Test: `tests/api/test_workspace_store.py`
- Test: `tests/api/test_task_api.py`

- [ ] Write failing tests for persistent empty workspace creation and a task request without workspace_id.
- [ ] Run focused tests and confirm the missing behavior.
- [ ] Allow empty workspace metadata and implement `FileSystemWorkspaceStore.create_empty()`.
- [ ] Make `workspace_id` optional at the HTTP request boundary and create the empty workspace server-side.
- [ ] Run focused backend tests.

### Task 2: Optional file selection in the launch page

**Files:**
- Modify: `frontend/src/components/WorkspaceForm.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Test: `frontend/src/App.test.tsx`

- [ ] Write a failing test that submits a prompt with no files and asserts no upload request occurs.
- [ ] Make empty file selection valid and label uploads as optional.
- [ ] Send task creation without workspace_id when the selected file list is empty.
- [ ] Run frontend tests and the production build.

### Task 3: Regression and live verification

**Files:**
- Modify: `README.md`
- Modify: `docs/16-项目开发日志.md`

- [ ] Run the complete Python suite.
- [ ] Run all frontend tests and the production build.
- [ ] Restart the local service and create a no-file task through the real HTTP API.
- [ ] Confirm the task appears in history and reports zero project files.
- [ ] Record the verified behavior and test totals.
