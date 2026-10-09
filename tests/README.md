# Test Suite

Tests are grouped by the primary boundary they verify:

| Directory | Scope |
|---|---|
| `contracts/` | Pydantic schemas, discriminators and cross-field invariants |
| `agent/` | Context construction, model calls, Decision parsing and one-step loop behavior |
| `tools/` | File, search, command and pytest execution primitives |
| `runtime/` | Action acceptance, permissions, dispatch and recovery |
| `state/` | Registries, aggregate views, transactions and SQLite restart behavior |
| `application/` | Application service and CLI entry points |
| `api/` | REST/SSE contracts, workspace handling and deployment assembly |
| `integration/` | Multi-component execution paths |
| `e2e/` | Complete task flows from request to verified result |

Run the full suite:

```bash
uv run pytest -q
```

Run one layer or one test:

```bash
uv run pytest -q tests/runtime
uv run pytest -q tests/e2e/test_forgemind_end_to_end.py
```
