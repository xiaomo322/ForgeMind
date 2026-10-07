# ForgeMind Deployable Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trusted-user deployable ForgeMind web application where a browser uploads Python files, creates a task, follows Agent progress over SSE, answers questions, and approves or rejects protected actions.

**Architecture:** FastAPI owns uploaded workspaces, SQLite task state, Agent execution, REST actions, SSE, and production static-file hosting. A React + TypeScript frontend calls same-origin APIs and renders an auditable timeline. A multi-stage Docker image builds the frontend and runs one Uvicorn process with persistent `/data` storage.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, python-multipart, React, TypeScript, Vite, Vitest, CSS, Docker.

## Global Constraints

- Deployment is for one trusted user or a private network; public multi-tenant arbitrary-code execution is outside scope.
- Browser APIs never accept or expose the server's absolute `project_root`.
- Uploads accept 1-20 flat UTF-8 `.py` files, at most 1 MiB each and 5 MiB total.
- Agent, Runtime, Tool, SQLite state, CLI local-path behavior, and per-Action permissions remain authoritative.
- All new backend behavior follows test-first development and the full Python regression must remain green.
- Frontend production assets are served by FastAPI from the same origin.

---

### Task 1: Filesystem uploaded workspace store

**Files:**
- Create: `backend/forgemind/web/workspaces.py`
- Test: `tests/api/test_workspace_store.py`

**Interfaces:**
- Produces: `UploadedFileInfo`, `UploadedWorkspace`, `WorkspaceUpload`, `FileSystemWorkspaceStore.create(uploads)`, and `FileSystemWorkspaceStore.resolve(workspace_id)`.
- `WorkspaceUpload` contains `filename: str` and `content: bytes`; the HTTP layer converts `UploadFile` into this transport-independent type.

- [ ] Write failing tests for one file, multiple files, restart resolution, invalid names, extension, UTF-8, duplicates, per-file size, total size, and maximum count.
- [ ] Run `.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\workspace-store-red tests/api/test_workspace_store.py` and verify missing imports fail.
- [ ] Implement immutable Pydantic response models, typed domain errors, streaming-independent validation, temporary-directory writes, cleanup on failure, and atomic rename to `workspace_<uuid>`.
- [ ] Run the same test command with `workspace-store-green` and verify every failure leaves no final workspace.
- [ ] Commit `backend/forgemind/web/workspaces.py` and `tests/api/test_workspace_store.py` as `feat: add isolated uploaded workspaces`.

### Task 2: Multipart workspace API

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `backend/forgemind/web/agent_api.py`
- Create: `tests/api/test_workspace_api.py`

**Interfaces:**
- Adds `POST /workspaces` with `files: list[UploadFile]` and HTTP 201 `UploadedWorkspace` response.
- `create_agent_stream_app(application, workspace_store)` receives the store explicitly.

- [ ] Add a failing TestClient multipart test using `files=[("files", ("calculator.py", b"def add(a, b):\n    return a + b\n", "text/x-python"))]`.
- [ ] Verify the route is absent or factory signature is missing.
- [ ] Add `python-multipart` and implement the route, reading each upload with a bounded `MAX_FILE_SIZE + 1` limit before calling the store.
- [ ] Map upload errors to 409, 413, 415, or 422 without absolute paths in `detail`.
- [ ] Run workspace store and API tests, then commit as `feat: expose workspace upload API`.

### Task 3: Create tasks from workspace IDs

**Files:**
- Modify: `backend/forgemind/web/agent_api.py`
- Modify: `tests/api/test_task_api.py`

**Interfaces:**
- `CreateTaskRequest(original_request: str, workspace_id: str)` replaces the Web-only `project_root` request field.
- `CreatedTaskResponse` returns `task_id`, `original_request`, `workspace_id`, `status`, and `revision`; it never exposes `project_root`.

- [ ] Rewrite the existing happy-path API test to upload a workspace first and create a task with its ID; assert the internal TaskRecord root equals `workspace_store.resolve(id)`.
- [ ] Add a failing unknown-workspace test expecting 404 and zero SQLite tasks.
- [ ] Update the request/response models and route while leaving `ForgeMindApplication.create_task(Path)` and CLI unchanged.
- [ ] Run `tests/api/test_task_api.py` and commit as `feat: create web tasks from uploaded workspaces`.

### Task 4: Task state and permission APIs

**Files:**
- Create: `backend/forgemind/web/public_models.py`
- Modify: `backend/forgemind/web/agent_api.py`
- Create: `tests/api/test_task_state_api.py`
- Create: `tests/api/test_permission_api.py`

**Interfaces:**
- Adds `GET /tasks/{task_id}` returning task ID, original request, current status, revision, and JSON-safe Action history without `project_root`.
- Adds `POST /tasks/{task_id}/permissions/{permission_request_id}` with `{decision: "approve" | "reject", raw_response: str}`.
- Permission response returns updated public task state.

- [ ] Write a failing state test proving the response can restore a waiting question and does not contain the internal root.
- [ ] Implement the public state mapper with `jsonable_encoder` for Action history.
- [ ] Write failing approve/reject tests against real SQLite waiting state, checking file effects and state transitions.
- [ ] Implement permission routing through `application.decide_permission()` and map missing/stale references to 404/409.
- [ ] Run both API test files and commit as `feat: expose task state and permission decisions`.

### Task 5: Frontend-ready SSE terminal and permission events

**Files:**
- Modify: `backend/forgemind/web/agent_events.py`
- Modify: `tests/api/test_agent_step_events.py`

**Interfaces:**
- Adds `task.permission_required`, `task.completed`, and `task.failed` public event types.
- Permission events contain `permission_request_id`, `tool_name`, reason, and relative action arguments.
- Completed events contain the final summary; failed events contain a public error category and message.

- [ ] Add failing tests for edit permission waiting, completion after `agent.step`, and an execution exception converted to `task.failed`.
- [ ] Implement explicit event builders and generator branches for all three permission waiting result classes and completion.
- [ ] Keep model hidden reasoning and server absolute paths out of all events.
- [ ] Run SSE tests and commit as `feat: complete task event protocol`.

### Task 6: Production FastAPI application

**Files:**
- Create: `backend/forgemind/web/app.py`
- Create: `tests/api/test_web_app.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces `create_web_app(settings: WebSettings) -> FastAPI` and module-level `app` for Uvicorn.
- `WebSettings` reads `FORGEMIND_DATA_DIR`, `FORGEMIND_MODEL_CONFIG`, `FORGEMIND_STATIC_DIR`, and optional `FORGEMIND_CORS_ORIGINS`.
- Adds console command `forgemind-web = forgemind.web.app:main`.

- [ ] Write failing tests using temporary data/config/static directories; verify SQLite and workspaces live below the data directory.
- [ ] Implement state/model/application/store wiring and narrowly configured CORS for development origins.
- [ ] Mount built static assets after API routes and return `index.html` for frontend paths without swallowing `/tasks` or `/workspaces`.
- [ ] Test app construction and command argument generation without calling an external model.
- [ ] Run API tests and commit as `feat: add production web application`.

### Task 7: React TypeScript frontend foundation

**Files:**
- Create: `frontend/package.json`, `frontend/pnpm-lock.yaml`, `frontend/index.html`, `frontend/tsconfig.json`, `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/taskState.ts`
- Create: `frontend/src/taskState.test.ts`

**Interfaces:**
- `uploadWorkspace(files: File[])`, `createTask(request, workspaceId)`, `getTask(taskId)`, `answerQuestion(...)`, and `decidePermission(...)` call same-origin APIs.
- `connectTaskEvents(taskId, callbacks)` owns `EventSource` lifecycle.
- A pure reducer converts public task events into UI timeline state.

- [ ] Initialize Vite React TypeScript with pnpm and add Vitest plus Testing Library.
- [ ] Write failing reducer tests for step, question, permission, completion, and failure events.
- [ ] Implement strict TypeScript discriminated unions, fetch error parsing, and the reducer.
- [ ] Run `pnpm --dir frontend test` and `pnpm --dir frontend build`; commit as `feat: add web client data layer`.

### Task 8: Complete user interface

**Files:**
- Create: `frontend/src/components/WorkspaceForm.tsx`
- Create: `frontend/src/components/TaskTimeline.tsx`
- Create: `frontend/src/components/UserPrompt.tsx`
- Create: `frontend/src/components/PermissionPrompt.tsx`
- Create: `frontend/src/components/StatusHeader.tsx`
- Create: `frontend/src/styles.css`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`

**Interfaces:**
- The start screen accepts `.py` files and a task description, shows selected file names/sizes, uploads, creates the task, and enters the timeline.
- Timeline cards render Agent reason, Tool name, arguments, Observation status, question options, permission actions, completion, and errors.
- Refresh restoration uses a task ID persisted in the URL query and `GET /tasks/{task_id}`.

- [ ] Write UI tests for upload validation, successful transition to a task, answering a question, and approving/rejecting permission.
- [ ] Implement accessible forms, keyboard focus, loading/disabled states, inline errors, responsive layout, and semantic status colors.
- [ ] Avoid hidden chain-of-thought language; label model `reason` as “决策依据”.
- [ ] Run frontend tests/build and inspect the built UI in a real browser at desktop and narrow widths.
- [ ] Commit as `feat: add ForgeMind web interface`.

### Task 9: Single-server container deployment

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `compose.yaml`
- Create: `.env.example`
- Modify: `README.md`
- Create: `tests/api/test_static_app.py`

**Interfaces:**
- Multi-stage image builds `frontend/dist`, installs ForgeMind, and starts `uvicorn forgemind.web.app:app --host 0.0.0.0 --port 8000`.
- Compose mounts `forgemind-data:/data`, supplies `DEEPSEEK_API_KEY`, and maps port 8000.

- [ ] Add a failing static-hosting test for `/` and an SPA route.
- [ ] Implement container files and trusted-user deployment documentation, including persistence, API key, model config, health check, backup, and the lack of public code-execution isolation.
- [ ] Run Python tests, frontend tests/build, Docker build when Docker is available, and a local HTTP smoke test.
- [ ] Commit as `feat: package deployable ForgeMind web app`.

### Task 10: Final end-to-end verification

**Files:**
- Create: `tests/e2e/test_web_uploaded_agent_flow.py`
- Modify: `docs/16-项目开发日志.md`
- Modify: `README.md`

**Interfaces:**
- Covers upload → task creation → SSE read → permission/user interaction → completion using real FastAPI, filesystem workspace, SQLite, and a deterministic fake model.

- [ ] Write the end-to-end test with visible UTF-8 diagnostic output and exact public API assertions.
- [ ] Run focused E2E, all Python tests, frontend tests, TypeScript build, and production static smoke test.
- [ ] Record exact verification counts and deployment limits in project documentation.
- [ ] Review the final diff for absolute-path leaks, secrets, unrelated changes, and stale instructions.
- [ ] Commit as `test: verify deployable web workflow`.
