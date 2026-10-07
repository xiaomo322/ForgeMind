# Test Suite Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize ForgeMind tests by responsibility without changing their behavior.

**Architecture:** Keep project tests under `tests/`, grouped by the component or boundary they primarily verify. Move standalone FastAPI exercises to `learning/fastapi/`, outside pytest's configured project test path.

**Tech Stack:** Python 3.11+, pytest 8.3.4, uv, Git

## Global Constraints

- Do not modify production code or test assertions.
- Preserve the user's existing changes in `backend/forgemind/agent/loop.py` and `examples/calculator_demo/calculator.py`.
- Preserve the verified pre-move baseline of 611 passing tests and include the user's concurrently added SSE delay test, for 612 tests after the move.
- Keep historical plan documents unchanged.

---

### Task 1: Record the test taxonomy

**Files:**
- Create: `tests/README.md`

**Interfaces:**
- Consumes: the approved responsibility-first directory design
- Produces: the canonical guide for locating and running tests

- [x] **Step 1:** Document every test category and give focused and full-suite pytest commands.
- [x] **Step 2:** Check that all listed directory names match the directories created in Task 2.

### Task 2: Move formal ForgeMind tests

**Files:**
- Move: `tests/test_*.py` into `tests/contracts/`, `tests/agent/`, `tests/tools/`, `tests/runtime/`, `tests/state/`, `tests/application/`, `tests/api/`, `tests/integration/`, or `tests/e2e/`

**Interfaces:**
- Consumes: pytest recursive discovery under `tests/`
- Produces: the same test functions at responsibility-based paths

- [x] **Step 1:** Create the nine approved category directories.
- [x] **Step 2:** Move pure data-contract tests to `tests/contracts/`.
- [x] **Step 3:** Move focused component tests to `agent`, `tools`, `runtime`, `state`, `application`, and `api`.
- [x] **Step 4:** Move cross-component flows to `integration` and the whole product flow to `e2e`.
- [x] **Step 5:** Run `pytest --collect-only` and verify 612 cases are collected: the 611-case baseline plus one concurrently added SSE delay test.

### Task 3: Separate FastAPI exercises

**Files:**
- Move: `tests/FastAPI学习/main.py` to `learning/fastapi/main.py`
- Move: `tests/FastAPI学习/test_main.py` to `learning/fastapi/test_main.py`
- Move: `tests/test_fastapi.py` to `learning/fastapi/first_route.py`
- Create: `learning/fastapi/README.md`

**Interfaces:**
- Consumes: standalone FastAPI examples
- Produces: learning files outside the ForgeMind regression suite

- [x] **Step 1:** Move the learning files without editing their implementation.
- [x] **Step 2:** Document how to run the developed FastAPI exercise directly.
- [x] **Step 3:** Verify default project test collection does not include `learning/fastapi/`.

### Task 4: Verify and review

**Files:**
- Verify: `tests/`
- Verify: `learning/fastapi/`

**Interfaces:**
- Consumes: the reorganized tree
- Produces: evidence that behavior and collection are preserved

- [x] **Step 1:** Run each top-level test category separately; all nine categories pass.
- [x] **Step 2:** Run the complete ForgeMind regression suite; 612 tests pass.
- [x] **Step 3:** Run the FastAPI learning test directly; 5 pass and the unfinished PATCH route exercise fails with the expected 405 response.
- [x] **Step 4:** Inspect the staged diff and status; unrelated edits remain unstaged. The scoped reorganization diff is clean.
