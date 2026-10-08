# ForgeMind Codex-Style Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent Codex-style task conversation with safe follow-up messages, staged Python attachments, an in-conversation execution timeline, and a project-files drawer.

**Architecture:** Keep `TaskRecord.original_request` immutable and append user follow-ups as separately sequenced SQLite facts. Upload new files into an isolated staging area; only publish them at the Agent loop safe boundary, before the next model call, using a recoverable publish plan and SHA-256 reconciliation. Expose the new facts through strict FastAPI models, then replace the two-column React workbench with a single conversation timeline and fixed composer.

**Tech Stack:** Python 3.11, Pydantic v2, SQLite, FastAPI, React 18, TypeScript, Vitest, pytest

## Global Constraints

- Continue the existing trusted-single-user / controlled-intranet deployment boundary.
- Accept only flat UTF-8 `.py` files: at most 20 active plus reserved staged names, at most 1 MiB per file, and at most 5 MiB per upload batch.
- Never expose the server's absolute workspace or staging paths through public models, SSE, logs returned to the browser, or file listings.
- Never overwrite an active or staged file with the same case-insensitive name; return a stable conflict instead.
- A message sent during an Agent/Tool step remains queued until that whole step has persisted its Action/permission/Observation facts.
- A queued attachment remains outside the active Workspace until the same safe boundary.
- User text never implies approval for `edit_file`, `run_tests`, or `run_command`; existing permission IDs remain authoritative.
- Preserve `TaskRecord.original_request`; all follow-ups are append-only facts.
- Preserve existing API Key isolation and subprocess environment allowlist.
- Run Python tests with `.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=<fresh path>` on Windows.

---

## File Structure

### New Python modules

- `backend/forgemind/workspace/__init__.py`: exports core workspace storage types without making Runtime depend on the Web package.
- `backend/forgemind/workspace/files.py`: active-file listing, staged-file write/delete, atomic publish, SHA-256 reconciliation, and workspace membership checks.
- `backend/forgemind/schema/messages.py`: immutable task message, staged attachment, publish plan, application fact, and message-state view contracts.
- `backend/forgemind/state/sqlite_task_message_registry.py`: message sequence allocation, lookup, application lookup, and table creation.
- `backend/forgemind/state/sqlite_staged_attachment_registry.py`: staged attachment and publish-plan persistence.
- `backend/forgemind/runtime/task_messages.py`: accept follow-up, prepare/apply queued messages, reopen completed/blocked tasks, and reject cancelled tasks.
- `frontend/src/components/MessageComposer.tsx`: text entry, staged file chips, answer mode, submission state, and retry state.
- `frontend/src/components/ProjectFilesDrawer.tsx`: accessible desktop/mobile drawer for active and staged files.
- `frontend/src/components/ConversationTimeline.tsx`: merge original request, user follow-ups, Agent reasons, Tool cards, questions, permissions, and completion cards.

### Existing modules to modify

- `backend/forgemind/web/workspaces.py`: become a compatibility re-export for core workspace types so existing imports keep working.
- `backend/forgemind/schema/tasks.py`: add explicit message state to `TaskStateView`.
- `backend/forgemind/schema/context.py`: add bounded applied-message context metadata.
- `backend/forgemind/context/builder.py`: select recent applied messages and report omissions.
- `backend/forgemind/state/sqlite_state.py`: construct new registries and provide transactional message methods.
- `backend/forgemind/application.py`: accept messages and apply/recover them at loop boundaries.
- `backend/forgemind/web/public_models.py`: publish safe message and attachment summaries.
- `backend/forgemind/web/agent_api.py`: add files/messages routes and map stable domain errors.
- `backend/forgemind/web/agent_events.py`: apply queued messages between completed loop steps and before the next model call.
- `frontend/src/types.ts`: add message, attachment, file-listing, and API response types.
- `frontend/src/api.ts`: add stage/list/delete/send calls.
- `frontend/src/taskState.ts`: hydrate and merge persistent conversation facts.
- `frontend/src/App.tsx`: orchestrate composer, drawer, interaction cards, and SSE resumption.
- `frontend/src/styles.css`: implement the approved dark single-column layout and responsive drawer.
- `README.md` and `docs/16-项目开发日志.md`: record verified behavior and real test output only after implementation.

---

### Task 1: Core Workspace Staging Boundary

**Files:**
- Create: `backend/forgemind/workspace/__init__.py`
- Create: `backend/forgemind/workspace/files.py`
- Modify: `backend/forgemind/web/workspaces.py`
- Test: `tests/api/test_workspace_store.py`

**Interfaces:**
- Consumes: existing `WorkspaceUpload`, `UploadedWorkspace`, upload limits, and `FileSystemWorkspaceStore.create()/resolve()` behavior.
- Produces: `StagedWorkspaceFile`, `WorkspaceFileInfo`, `WorkspaceFileListing`, `FileSystemWorkspaceStore.stage()`, `.publish()`, `.delete_staged()`, `.list_files()`, and `.require_managed_workspace()`.

- [ ] **Step 1: Add failing staging tests**

```python
def test_staged_file_is_not_visible_inside_active_workspace(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    project_root = store.resolve(workspace.workspace_id)

    staged = store.stage(
        task_id="task-1",
        project_root=project_root,
        uploads=[WorkspaceUpload("extra.py", b"extra = 2\n")],
        next_upload_id=lambda: "upload-1",
    )

    assert staged[0].path == "extra.py"
    assert staged[0].sha256 == hashlib.sha256(b"extra = 2\n").hexdigest()
    assert not (project_root / "extra.py").exists()
    assert store.list_files(project_root, staged=staged).files[-1].state == "staged"


def test_publish_moves_exact_staged_bytes_into_workspace(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    project_root = store.resolve(workspace.workspace_id)
    staged = store.stage(
        task_id="task-1",
        project_root=project_root,
        uploads=[WorkspaceUpload("extra.py", b"extra = 2\n")],
        next_upload_id=lambda: "upload-1",
    )
    store.publish(project_root, staged[0])
    assert (project_root / "extra.py").read_bytes() == b"extra = 2\n"
    assert store.reconcile_publish(project_root, staged[0]) == "published"


def test_stage_rejects_name_already_active_or_reserved(tmp_path: Path) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    project_root = store.resolve(workspace.workspace_id)
    with pytest.raises(DuplicateWorkspaceFilenameError):
        store.stage(
            task_id="task-1",
            project_root=project_root,
            uploads=[WorkspaceUpload("APP.py", b"changed = True\n")],
            next_upload_id=lambda: "upload-1",
        )
    assert (project_root / "app.py").read_bytes() == b"value = 1\n"
```

- [ ] **Step 2: Run the focused tests and observe the red failure**

Run:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-stage-red tests/api/test_workspace_store.py
```

Expected: imports or methods for staging are missing; existing workspace tests still collect.

- [ ] **Step 3: Move the storage implementation into the core package**

Define these strict public values in `workspace/files.py`:

```python
@dataclass(frozen=True, slots=True)
class StagedWorkspaceFile:
    upload_id: str
    task_id: str
    path: str
    size_bytes: int
    sha256: str
    staging_token: str  # internal opaque token; never placed in Web models


class WorkspaceFileInfo(StrictContractModel):
    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["active", "staged"]


class WorkspaceFileListing(StrictContractModel):
    files: tuple[WorkspaceFileInfo, ...]
    file_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
```

`stage()` validates the complete batch before writing, writes under the store-controlled `.staged` directory, computes SHA-256 from exact bytes, reserves case-folded names against active and supplied staged records, and returns immutable records. `publish()` resolves both source and destination beneath controlled roots, rejects an existing destination, and uses `Path.replace()` on the same storage volume. `reconcile_publish()` returns `"staged"` when only the staged file exists, `"published"` when only a matching destination exists, and raises a stable integrity error for missing or hash-mismatched bytes.

- [ ] **Step 4: Preserve the existing import surface**

`web/workspaces.py` imports and re-exports the core names so current `agent_api.py` and tests continue to work while new Runtime code imports only `forgemind.workspace`.

- [ ] **Step 5: Run focused and existing Workspace API tests**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-stage-green tests/api/test_workspace_store.py tests/api/test_workspace_api.py
```

Expected: staged bytes are absent from the active root before publish, exact after publish, and all pre-existing upload limits still pass.

- [ ] **Step 6: Commit the slice**

```powershell
git add backend/forgemind/workspace backend/forgemind/web/workspaces.py tests/api/test_workspace_store.py
git commit -m "feat: stage workspace attachments safely"
```

### Task 2: Persistent Follow-Up Message Facts

**Files:**
- Create: `backend/forgemind/schema/messages.py`
- Create: `backend/forgemind/state/sqlite_task_message_registry.py`
- Create: `backend/forgemind/state/sqlite_staged_attachment_registry.py`
- Modify: `backend/forgemind/schema/tasks.py`
- Modify: `backend/forgemind/state/sqlite_state.py`
- Test: `tests/state/test_sqlite_task_message_registry.py`
- Test: `tests/state/test_sqlite_staged_attachment_registry.py`

**Interfaces:**
- Consumes: `TaskRecord`, SQLite task foreign keys, `open_sqlite_connection()`.
- Produces: `TaskMessageRecord`, `TaskMessageApplicationRecord`, `StagedAttachmentRecord`, `AttachmentPublishPlan`, `TaskMessageStateView`, `state.record_task_message()`, and message/staging registries.

- [ ] **Step 1: Write contract and restart-recovery tests**

```python
message = TaskMessageRecord(
    message_id="message-1",
    task_id=task.task_id,
    sequence=1,
    content="同时检查折扣为 0",
    attachment_upload_ids=("upload-1",),
)
state.record_task_message(message)
reopened = SQLiteForgeMindState.open(database_path)
assert reopened.task_messages.list_for_task(task.task_id) == (message,)
assert reopened.get_task_view(task.task_id).messages[0].application is None
```

Add named tests `test_message_requires_text_or_attachment()`, `test_duplicate_message_id_does_not_overwrite()`, `test_message_sequence_must_be_contiguous()`, `test_message_requires_existing_task()`, `test_upload_can_only_be_attached_once()`, and `test_application_must_match_message_task()`. Each test first records a valid control row, performs one invalid write inside `pytest.raises(<specific domain error>)`, then reopens SQLite and asserts the control row is unchanged.

- [ ] **Step 2: Run and observe missing-schema failures**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-state-red tests/state/test_sqlite_task_message_registry.py tests/state/test_sqlite_staged_attachment_registry.py
```

- [ ] **Step 3: Add immutable Pydantic contracts**

Use a model validator so `content is None or not content.strip()` is accepted only when at least one upload ID exists. Keep the original non-blank content unchanged. `TaskMessageStateView` always receives `application: TaskMessageApplicationRecord | None` explicitly.

- [ ] **Step 4: Add SQLite tables and strict restore checks**

Create tables with task foreign keys and unique constraints on `(task_id, sequence)`, `message_id`, `upload_id`, and `message_applications.message_id`. Store full `payload_json` plus queryable identity columns, then cross-check restored JSON against those columns exactly as existing Action registries do.

- [ ] **Step 5: Integrate registries into `SQLiteForgeMindState.open()` and `get_task_view()`**

Add fields:

```python
task_messages: SQLiteTaskMessageRegistry
staged_attachments: SQLiteStagedAttachmentRegistry
```

`get_task_view()` supplies an explicit ordered `messages=tuple(...)`; existing TaskStateView constructors and tests must explicitly pass `messages=()`.

- [ ] **Step 6: Run state tests and commit**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-state-green tests/state/test_sqlite_task_message_registry.py tests/state/test_sqlite_staged_attachment_registry.py
git add backend/forgemind/schema/messages.py backend/forgemind/schema/tasks.py backend/forgemind/state tests/state/test_sqlite_task_message_registry.py tests/state/test_sqlite_staged_attachment_registry.py
git commit -m "feat: persist task follow-up messages"
```

### Task 3: Runtime Acceptance and Recoverable Attachment Publication

**Files:**
- Create: `backend/forgemind/runtime/task_messages.py`
- Modify: `backend/forgemind/runtime/ids.py`
- Modify: `backend/forgemind/state/sqlite_state.py`
- Test: `tests/runtime/test_task_messages.py`
- Test: `tests/integration/test_attachment_publish_recovery.py`

**Interfaces:**
- Consumes: Task 1 store methods and Task 2 records/registries.
- Produces: `accept_task_message()`, `prepare_queued_messages()`, `finish_prepared_messages()`, and `recover_prepared_messages()`.

- [ ] **Step 1: Write safe-boundary and crash-recovery tests**

Verify that acceptance only writes a queued message, preparing writes a publish plan before filesystem movement, finishing adds applications after matching bytes exist, and recovery completes a plan when the destination hash matches. A mismatched destination must raise `AttachmentPublishIntegrityError` and leave the message unapplied.

```python
accepted = accept_task_message(
    task_id=task.task_id,
    content="检查 extra.py",
    attachment_upload_ids=(staged.upload_id,),
    state=state,
    next_message_id=lambda: "message-1",
)
assert state.get_task_view(task.task_id).messages[0].application is None

prepared = prepare_queued_messages(task.task_id, state=state)
assert prepared.publish_plan is not None
assert not (project_root / "extra.py").exists()

store.publish(project_root, staged)
finish_prepared_messages(prepared, state=state, workspace_store=store)
view = state.get_task_view(task.task_id)
assert view.messages[0].application.applied_after_action_sequence == 0
assert (project_root / "extra.py").read_bytes() == b"extra = 2\n"
```

- [ ] **Step 2: Run the runtime tests red**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-runtime-red tests/runtime/test_task_messages.py tests/integration/test_attachment_publish_recovery.py
```

- [ ] **Step 3: Implement authoritative ID and sequence allocation**

`accept_task_message()` accepts content plus upload IDs, restores each upload from State, checks task ownership and single-message use, then allocates `message_id` and the next task-local sequence inside `state.record_new_task_message(...)`. Client IDs or timestamps never decide ordering.

- [ ] **Step 4: Implement the publication state machine**

```text
queued message
  → PREPARED publish plan persisted
  → store.publish() / reconcile_publish()
  → TaskMessageApplicationRecord persisted
  → prepared plan considered complete because application now exists
```

Pure-text messages skip the filesystem plan. Every application records the current Action count as `applied_after_action_sequence`.

- [ ] **Step 5: Implement explicit continuation rules**

`RUNNING`, `WAITING_USER`, and `EXECUTING` accept queued messages without changing status. At a safe boundary, `COMPLETED` and `BLOCKED` messages are applied with a new sequential `RUNNING` status. `CANCELLED` raises `CancelledTaskCannotContinueError`. This special transaction is the only legal completed/blocked continuation path; do not widen the general transition table.

- [ ] **Step 6: Run tests and commit**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-runtime-green tests/runtime/test_task_messages.py tests/integration/test_attachment_publish_recovery.py
git add backend/forgemind/runtime backend/forgemind/state/sqlite_state.py tests/runtime/test_task_messages.py tests/integration/test_attachment_publish_recovery.py
git commit -m "feat: apply queued messages at safe boundaries"
```

### Task 4: Agent Context and Loop Safe Boundary

**Files:**
- Modify: `backend/forgemind/schema/context.py`
- Modify: `backend/forgemind/context/builder.py`
- Modify: `backend/forgemind/application.py`
- Modify: `backend/forgemind/web/agent_events.py`
- Test: `tests/agent/test_context_builder.py`
- Test: `tests/application/test_follow_up_message_loop.py`

**Interfaces:**
- Consumes: applied message views and Runtime application functions.
- Produces: `AgentTaskContext.recent_messages`, explicit message counts, and loop behavior that applies/reconciles queued messages only between steps.

- [ ] **Step 1: Write a controlled concurrency test**

Use a blocking fake Tool/model boundary: start one step, accept a message while it is blocked, release it, then capture both model inputs. Assert the first input lacks the follow-up, the first Action/Observation completes unchanged, and the second input contains the exact follow-up and attachment path.

- [ ] **Step 2: Run the focused tests red**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-loop-red tests/agent/test_context_builder.py tests/application/test_follow_up_message_loop.py
```

- [ ] **Step 3: Extend bounded Context**

Add `max_message_count` to `build_agent_task_context()`. Include only applied messages, preserve server sequence, and calculate `total_message_count`, `omitted_message_count`, and `is_message_history_complete` independently from Action limits.

- [ ] **Step 4: Add the boundary to the application loop**

Before the first model call and after each completed `run_agent_loop_step()`, recover any prepared publish plan and apply the queued snapshot. Messages arriving after the snapshot stay queued for the next boundary. Do not hold a SQLite transaction during model or Tool execution.

- [ ] **Step 5: Run tests and commit**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-loop-green tests/agent/test_context_builder.py tests/application/test_follow_up_message_loop.py
git add backend/forgemind/schema/context.py backend/forgemind/context/builder.py backend/forgemind/application.py backend/forgemind/web/agent_events.py tests/agent/test_context_builder.py tests/application/test_follow_up_message_loop.py
git commit -m "feat: feed follow-ups into agent turns"
```

### Task 5: Task Files and Messages HTTP API

**Files:**
- Modify: `backend/forgemind/web/public_models.py`
- Modify: `backend/forgemind/web/agent_api.py`
- Modify: `backend/forgemind/web/request_limits.py`
- Test: `tests/api/test_task_file_api.py`
- Test: `tests/api/test_task_message_api.py`
- Test: `tests/api/test_task_state_api.py`

**Interfaces:**
- Consumes: Application message entry point, staged file store, and TaskStateView messages.
- Produces: `GET/POST /tasks/{task_id}/files`, staged delete, `POST /tasks/{task_id}/messages`, and message projection in `GET /tasks/{task_id}`.

- [ ] **Step 1: Write API contract tests**

Create separate named tests for successful staging, list states, delete-unreferenced upload, message acceptance, same-task attachment ownership, 404 task, 409 duplicate name, 409 cancelled task, public path redaction, and completed-task continuation. The central request/response assertion is:

```python
staged = client.post(
    f"/tasks/{task_id}/files",
    files=[("files", ("extra.py", b"extra = 2\n", "text/x-python"))],
)
assert staged.status_code == 201
upload_id = staged.json()["uploads"][0]["upload_id"]

sent = client.post(
    f"/tasks/{task_id}/messages",
    json={"content": "检查新文件", "attachment_upload_ids": [upload_id]},
)
assert sent.status_code == 202
assert sent.json()["delivery"] == "queued"
assert str(workspace_store.storage_root) not in sent.text
```

- [ ] **Step 2: Run API tests red**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-api-red tests/api/test_task_file_api.py tests/api/test_task_message_api.py
```

- [ ] **Step 3: Add strict request/response models and routes**

`CreateTaskMessageRequest` uses a model validator requiring non-blank `content` or at least one upload ID. The files endpoint receives multipart data under the same body middleware. Domain ownership/conflict errors map to 404/409/413/415/422 without returning internal paths.

- [ ] **Step 4: Extend public task projection**

Add `PublicTaskMessage` fields exactly matching the design. Convert internal staged records to safe summaries; never serialize `staging_token`.

- [ ] **Step 5: Run API tests and commit**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-message-api-green tests/api/test_task_file_api.py tests/api/test_task_message_api.py tests/api/test_task_state_api.py
git add backend/forgemind/web tests/api/test_task_file_api.py tests/api/test_task_message_api.py tests/api/test_task_state_api.py
git commit -m "feat: expose task messages and attachments"
```

### Task 6: Frontend Conversation State and API Client

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/taskState.ts`
- Modify: `frontend/src/taskState.test.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Consumes: Task 5 JSON contracts.
- Produces: `stageTaskFiles()`, `listTaskFiles()`, `deleteStagedFile()`, `sendTaskMessage()`, and a deterministic conversation timeline state.

- [ ] **Step 1: Write failing reducer and API tests**

Assert that applied messages are positioned after their boundary Action, queued messages remain at the bottom with a badge, and page hydration restores attachments without optimistic duplicates.

```typescript
it("places an applied message after its recorded action boundary", () => {
  const state = hydrateTaskUiState(taskWithMessage({
    sequence: 2,
    delivery: "applied",
    applied_after_action_sequence: 1,
  }));
  expect(state.timeline.map((item) => item.kind)).toEqual([
    "user-message", "agent-step", "user-message",
  ]);
});

it("keeps queued messages after persisted actions", () => {
  const state = hydrateTaskUiState(taskWithMessage({
    sequence: 2,
    delivery: "queued",
    applied_after_action_sequence: null,
  }));
  expect(state.timeline.at(-1)).toMatchObject({ kind: "user-message", delivery: "queued" });
});
```

- [ ] **Step 2: Run Vitest red**

```powershell
cd frontend
pnpm test -- --run
```

- [ ] **Step 3: Add exact TypeScript contracts and API functions**

Use `FormData` for files and JSON for messages. Preserve the successful staged response when message POST fails so `MessageComposer` can retry using the same upload IDs.

- [ ] **Step 4: Build the deterministic timeline merge**

Use `applied_after_action_sequence` and message sequence; do not sort by random IDs or client timestamps. The original request is sequence zero, queued messages are appended after persisted Action history, and permission/question records remain visible after response.

- [ ] **Step 5: Run tests and commit**

```powershell
pnpm test -- --run
cd ..
git add frontend/src/types.ts frontend/src/api.ts frontend/src/taskState.ts frontend/src/taskState.test.ts frontend/src/api.test.ts
git commit -m "feat: model persistent task conversation"
```

### Task 7: Approved Codex-Style React Interface

**Files:**
- Create: `frontend/src/components/MessageComposer.tsx`
- Create: `frontend/src/components/ProjectFilesDrawer.tsx`
- Create: `frontend/src/components/ConversationTimeline.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: Task 6 API and conversation state.
- Produces: approved single-column conversation, inline Action/permission/question cards, fixed composer, and responsive files drawer.

- [ ] **Step 1: Write user-visible behavior tests**

Test attachment selection/removal, staged retry, drawer open/close, active/staged labels, sending while running, answer-mode routing to `/answers`, permission buttons routing only to the permission API, completed-task continuation, and refresh hydration.

```typescript
it("stages attachments before sending a follow-up", async () => {
  render(<App />);
  await userEvent.upload(screen.getByLabelText("添加 Python 文件"), pythonFile("extra.py"));
  await userEvent.type(screen.getByLabelText("继续输入任务要求"), "检查新文件");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(stageTaskFilesMock).toHaveBeenCalledWith(expect.any(String), [expect.objectContaining({ name: "extra.py" })]);
  expect(sendTaskMessageMock).toHaveBeenCalledWith(expect.any(String), "检查新文件", ["upload-1"]);
});

it("does not treat typed text as permission approval", async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText("继续输入任务要求"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(decidePermissionMock).not.toHaveBeenCalled();
  expect(sendTaskMessageMock).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run UI tests red**

```powershell
cd frontend
pnpm test -- --run
```

- [ ] **Step 3: Implement the components**

Keep native buttons, labels, focus management, `aria-live` status text, Escape-to-close drawer, and visible keyboard focus. Desktop drawer opens from the right; below 900 px it becomes a full-width overlay. Tool cards use native `<details>` so collapsed content remains keyboard accessible.

- [ ] **Step 4: Wire App orchestration**

On send: stage selected files, send the message with upload IDs, keep staged tokens on message failure, clear text/files only after message acceptance, update from the authoritative task snapshot, and reconnect SSE when the response makes the task runnable. In `WAITING_USER` ask mode, disable attachments and call the existing answer API. Permission cards remain separate.

- [ ] **Step 5: Run frontend verification and commit**

```powershell
pnpm test -- --run
.\node_modules\.bin\tsc.cmd --noEmit
pnpm build
cd ..
git add frontend/src
git commit -m "feat: add codex-style task conversation"
```

### Task 8: End-to-End Evidence, Documentation, and Full Regression

**Files:**
- Create: `tests/e2e/test_codex_style_conversation.py`
- Modify: `README.md`
- Modify: `docs/16-项目开发日志.md`

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: executable evidence for the complete safe-boundary flow and accurate project progress records.

- [ ] **Step 1: Write the full-flow test with visible evidence**

The fake model/tool barrier must prove: initial workspace creation; a follow-up and attachment accepted during an active step; staged file absent during that step; current Action result unchanged; file published at the next boundary; exact follow-up present in the next model input; completion; another follow-up reopening the same task ID; second completion; refresh restoring all messages, actions, and files.

- [ ] **Step 2: Run the focused E2E test with printed facts**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -s -p no:cacheprovider --basetemp=.test-tmp\pytest-conversation-e2e tests/e2e/test_codex_style_conversation.py
```

Expected output must identify the queued message ID, the Action sequence after which it became applied, the staged-to-active file transition, and the second completion on the same task ID.

- [ ] **Step 3: Run full backend and frontend regression**

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -p no:cacheprovider --basetemp=.test-tmp\pytest-conversation-full
cd frontend
pnpm test -- --run
.\node_modules\.bin\tsc.cmd --noEmit
pnpm build
cd ..
```

- [ ] **Step 4: Update progress from actual output**

Record only the observed test counts, build result, supported upload limits, continuation behavior, and remaining trusted-user deployment boundary. Do not copy expected counts into the log before commands finish.

- [ ] **Step 5: Review and commit**

```powershell
git diff --check
git add tests/e2e/test_codex_style_conversation.py README.md docs/16-项目开发日志.md
git commit -m "test: verify persistent agent conversation"
```

