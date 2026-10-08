# Persistent Workspaces and ZIP Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make persisted ForgeMind tasks discoverable and let users create or download complete project workspaces as ZIP archives.

**Architecture:** Extend the existing SQLite task registry with a read-only recent-task query and extend `FileSystemWorkspaceStore` with bounded ZIP import/export operations. Expose those capabilities through FastAPI, then add task-history and archive controls to the existing React workbench without introducing browser-owned persistence.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, Pydantic v2, `zipfile`, React 18, TypeScript, Vitest, Testing Library.

## Global Constraints

- A ZIP upload always creates a new isolated workspace.
- Task history is restored from SQLite, never from local storage.
- ZIP import must reject traversal, symlink, encrypted, duplicate and over-limit entries before publishing a workspace.
- ZIP export contains active workspace regular files only.
- Existing direct `.py` upload and staged-message attachment behavior must remain compatible.

---

### Task 1: Safe ZIP workspace import and export

**Files:**
- Modify: `backend/forgemind/web/workspaces.py`
- Test: `tests/api/test_workspace_store.py`

**Interfaces:**
- Produces: `FileSystemWorkspaceStore.create_from_zip(archive: bytes) -> UploadedWorkspace`
- Produces: `FileSystemWorkspaceStore.build_zip(project_root: Path) -> bytes`

- [ ] Add failing tests for nested ZIP extraction and round-trip export.
- [ ] Run the focused storage tests and confirm missing-method failures.
- [ ] Add failing rejection tests for `../`, absolute paths, symlinks, encrypted entries, duplicate normalized paths and expanded-size limits.
- [ ] Implement validation-first extraction into a temporary directory and atomic publication.
- [ ] Implement deterministic ZIP export from managed regular files.
- [ ] Run `uv run pytest tests/api/test_workspace_store.py -q`.

### Task 2: Persistent recent-task query

**Files:**
- Modify: `backend/forgemind/state/sqlite_task_registry.py`
- Modify: `backend/forgemind/state/sqlite_state.py`
- Test: `tests/state/test_sqlite_task_registry.py`

**Interfaces:**
- Produces: `SQLiteTaskRegistry.list_recent(limit: int) -> tuple[TaskRecord, ...]`
- Produces: `SQLiteForgeMindState.list_recent_tasks(limit: int) -> tuple[TaskStateView, ...]`

- [ ] Add a failing registry test that expects newest-first insertion order and a limit.
- [ ] Run the focused test and confirm the method is absent.
- [ ] Implement a parameterized `ORDER BY rowid DESC LIMIT ?` query with stored-contract validation.
- [ ] Add the state facade that builds current task views.
- [ ] Run focused state tests.

### Task 3: Task list and workspace archive HTTP APIs

**Files:**
- Modify: `backend/forgemind/web/agent_api.py`
- Modify: `backend/forgemind/web/request_limits.py`
- Test: `tests/api/test_workspace_api.py`
- Test: `tests/api/test_task_api.py`

**Interfaces:**
- Produces: `POST /workspaces/archive`
- Produces: `GET /tasks?limit=50`
- Produces: `GET /tasks/{task_id}/workspace.zip`

- [ ] Add failing API tests for ZIP upload, history after application restart, bounded list ordering and downloaded ZIP contents.
- [ ] Run the focused API tests and confirm 404/405 failures.
- [ ] Implement request parsing and stable HTTP error mapping for ZIP uploads.
- [ ] Implement public task summary models and the recent-task route.
- [ ] Implement archive download with safe `Content-Disposition` and no server-path disclosure.
- [ ] Run focused API tests.

### Task 4: React ZIP upload and task history UI

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/WorkspaceForm.tsx`
- Modify: `frontend/src/components/ProjectFilesDrawer.tsx`
- Create: `frontend/src/components/TaskHistoryDrawer.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: the three HTTP endpoints from Task 3.
- Produces: task history drawer, ZIP workspace creation and whole-workspace download controls.

- [ ] Add failing UI tests for selecting one ZIP, rejecting ZIP/file mixtures, opening persisted history, switching task URLs and rendering the download link.
- [ ] Run the focused Vitest suite and confirm failures for missing controls.
- [ ] Add typed API functions and task-summary types.
- [ ] Add the history drawer and make it available on both launch and workbench screens.
- [ ] Extend workspace creation to choose direct files or a ZIP archive.
- [ ] Add the ZIP download action to the project drawer.
- [ ] Add responsive styles and accessible labels/focus behavior.
- [ ] Run the frontend tests and production build.

### Task 5: Regression and browser verification

**Files:**
- Modify: `README.md`
- Modify: `docs/16-项目开发日志.md`

**Interfaces:**
- Consumes: all features from Tasks 1-4.
- Produces: current project progress and reproducible user workflow.

- [ ] Run the complete Python suite with `uv run pytest -q`.
- [ ] Run all frontend tests and `npm run build`.
- [ ] Restart the local app and upload a nested project ZIP.
- [ ] Create two tasks, switch between them from history, refresh, and verify both remain available.
- [ ] Download the active workspace ZIP and inspect its entries.
- [ ] Update README and the development log with the verified behavior and commands.
