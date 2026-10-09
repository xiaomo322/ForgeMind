# Security Model

ForgeMind treats the model, uploaded source code and Tool output as untrusted inputs. Security decisions are enforced by deterministic Runtime code rather than prompt instructions.

## Runtime controls

### Strict contracts

All model decisions and public requests pass through strict Pydantic models. Unknown fields, wrong types, missing arguments and invalid discriminators are rejected before an Action can be registered.

### Project path confinement

File and test targets are normalized against the task workspace. Absolute paths, parent traversal and paths that resolve outside the workspace are rejected. The browser only receives public workspace IDs and relative paths.

### Action-scoped permission

Approval references one persisted permission request, which in turn references one immutable Action and its complete parameters. Approval for an edit cannot authorize deletion, a different file, or a later Action.

### Version-bound edits

`edit_file` verifies the expected content hash, exact replacement count and target type immediately before writing. It writes through a temporary file in the same directory, flushes data and atomically replaces the target. If the file changed after planning, the Action fails without overwriting it.

### Controlled processes

`run_command` resolves a logical program name through a server-owned allowlist and invokes it with an argument vector, never through a shell string. Working directories remain inside the task workspace. Process output, time and size are bounded.

`run_tests` executes explicit pytest targets and records both process facts and parsed JUnit results. A successful process launch is separate from the test outcome.

### Secret isolation

Model credentials are loaded from a named server environment variable. Tool subprocesses receive a minimal allowlist of operating-system variables and do not inherit the model API key.

### Upload validation

Direct uploads accept bounded UTF-8 Python files. ZIP uploads are inspected before extraction and reject traversal paths, links, encryption, duplicates and resource-limit violations. New workspaces are published atomically only after validation succeeds.

### Public response filtering

API and SSE models expose public IDs, relative paths and bounded evidence. Server filesystem paths, Tool temporary directories and raw internal exceptions are not returned to the browser. The production app also sets CSP, frame, referrer and MIME-sniffing response headers.

## Deployment boundary

The supplied container runs as a non-root user with a read-only root filesystem, dropped Linux capabilities, `no-new-privileges`, a PID limit and a bounded temporary filesystem. Persistent state is restricted to `/data`.

These controls reduce risk but do not turn ForgeMind into a hostile-code sandbox. Tests and approved commands execute project Python code inside the application container. The current release is intended for a single trusted user or controlled team environment.

Before anonymous or multi-tenant deployment, add:

- per-task disposable containers or microVMs;
- CPU, memory, disk and wall-clock quotas;
- outbound network restrictions;
- authentication and tenant authorization;
- centralized audit logs and retention policy;
- malware/content scanning and abuse controls.

## Reporting a vulnerability

Do not publish credentials, private source code or exploit payloads in a public issue. Revoke any exposed credential immediately and provide a minimal reproduction with secrets removed.
