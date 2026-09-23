# Search Code V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个无需外部命令、能在项目范围内确定性搜索 Python 源码并把完整性事实记录到 State 的 `search_code` Tool。

**Architecture:** Agent 先产生严格的 SearchCode Decision，Runtime 分配 action_id、登记 AcceptedAction、解析并限制项目范围，然后 Tool 对排序后的 `.py` 候选逐行执行大小写敏感的普通文本匹配。Runtime 把实际结果或失败转换成唯一终态 Observation；达到结果上限或跳过文件时返回 success，但明确标记结果不完整。

**Tech Stack:** Python 3.13、pathlib、Pydantic v2、pytest。

## Global Constraints

- `query` 是非空普通字符串；V0.1 不支持正则、忽略大小写或 AST 语义搜索。
- `scope` 默认 `.`，必须解析到项目根目录内；单文件 scope 只允许 `.py`。
- `max_results` 默认 20，范围 1～100，只限制返回条目数。
- 目录搜索忽略 `.git`、`.venv`、`__pycache__`、`.test-tmp`。
- 候选文件按项目相对 POSIX 路径排序，文件内按从 1 开始的行号排序。
- 每个文件最多读取 64 KiB；越界、无法读取、非 UTF-8 或越出项目根目录的候选被跳过，并使结果不完整。
- 发现第 `max_results + 1` 条匹配才确认 `RESULT_LIMIT_REACHED`；恰好等于上限且扫描完成仍可完整。
- 每个生产代码切片遵循 RED → GREEN → REFACTOR；核心函数先写中文步骤注释，由学习者实现。

---

### Task 1: SearchCodeArguments 严格输入契约

**Files:**
- Create: `backend/forgemind/schema/search_code.py`
- Create: `tests/test_search_code_arguments.py`

**Interfaces:**
- Consumes: `StrictContractModel`。
- Produces: `DEFAULT_SEARCH_RESULTS = 20`、`MAX_SEARCH_RESULTS = 100`、`SearchCodeArguments`。

- [x] **Step 1: 写失败测试**

```python
def test_search_arguments_apply_controlled_defaults() -> None:
    arguments = SearchCodeArguments(query="discount")
    assert arguments.scope == "."
    assert arguments.max_results == 20


@pytest.mark.parametrize("max_results", [0, 101])
def test_search_arguments_reject_result_limit_outside_bounds(
    max_results: int,
) -> None:
    with pytest.raises(ValidationError):
        SearchCodeArguments(query="discount", max_results=max_results)
```

增加参数化测试，分别传入 `{"query": ""}`、`{"query": "x", "scope": ""}`、`{"query": 123}`、`{"query": "x", "max_results": "20"}` 和 `{"query": "x", "unknown": True}`，每组都断言抛出 `ValidationError`。

- [x] **Step 2: 运行 RED 测试**

Run: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-arguments tests\test_search_code_arguments.py`

Expected: FAIL，因为 `SearchCodeArguments` 尚不存在或没有字段约束。

- [x] **Step 3: 学习者实现最小 Schema**

```python
DEFAULT_SEARCH_RESULTS = 20
MAX_SEARCH_RESULTS = 100


class SearchCodeArguments(StrictContractModel):
    query: str = Field(min_length=1)
    scope: str = Field(default=".", min_length=1)
    max_results: int = Field(
        default=DEFAULT_SEARCH_RESULTS,
        ge=1,
        le=MAX_SEARCH_RESULTS,
    )
```

- [x] **Step 4: 运行聚焦与完整测试**

Expected: 新测试全部通过，完整测试不少于 122 项通过。

- [x] **Step 5: 提交检查点**

`git commit -m "feat: add search code argument contract"`

### Task 2: Match 与 Result 事实契约

**Files:**
- Modify: `backend/forgemind/schema/search_code.py`
- Create: `tests/test_search_code_result.py`

**Interfaces:**
- Consumes: `SearchCodeArguments` 的 query/scope/max_results 语义。
- Produces: `SearchIncompleteReason`、`SearchCodeMatch`、`SearchCodeResult`。

- [x] **Step 1: 写失败测试**

测试以下规则：line_number 从 1 开始；`returned_count == len(matches)`；完整结果没有 incomplete_reasons；不完整结果至少有一个原因；零匹配且完整是合法 success result。

```python
result = SearchCodeResult(
    query="discount",
    searched_scope=".",
    matches=(),
    returned_count=0,
    is_complete=True,
    incomplete_reasons=(),
)
assert result.matches == ()
```

再构造 `returned_count=1, matches=()`、`is_complete=True` 且带原因、`is_complete=False` 且原因为空三种对象，分别断言 `ValidationError`；构造 `SearchCodeMatch(path="a.py", line_number=0, line_text="x")` 并断言拒绝。

- [x] **Step 2: 运行 RED 测试**

Run: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-result tests\test_search_code_result.py`

Expected: FAIL，因为结果类型尚不存在。

- [x] **Step 3: 实现严格结果模型**

```python
class SearchIncompleteReason(StrEnum):
    RESULT_LIMIT_REACHED = "RESULT_LIMIT_REACHED"
    FILE_SKIPPED = "FILE_SKIPPED"


class SearchCodeMatch(StrictContractModel):
    path: str = Field(min_length=1)
    line_number: int = Field(ge=1)
    line_text: str


class SearchCodeResult(StrictContractModel):
    query: str = Field(min_length=1)
    searched_scope: str = Field(min_length=1)
    matches: tuple[SearchCodeMatch, ...]
    returned_count: int = Field(ge=0)
    is_complete: bool
    incomplete_reasons: tuple[SearchIncompleteReason, ...]
```

增加以下 validator，一次校验计数和完整性组合：

```python
@model_validator(mode="after")
def validate_result_consistency(self) -> Self:
    if self.returned_count != len(self.matches):
        raise ValueError("returned_count 必须等于 matches 数量")
    if self.is_complete and self.incomplete_reasons:
        raise ValueError("完整结果不能包含 incomplete_reasons")
    if not self.is_complete and not self.incomplete_reasons:
        raise ValueError("不完整结果必须说明原因")
    return self
```

- [x] **Step 4: 运行聚焦与完整测试**

Run focused: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-result tests\test_search_code_result.py`

Run full: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\full-suite`

- [x] **Step 5: 提交检查点**

`git commit -m "feat: define search code result contract"`

### Task 3: SearchCode Decision、AcceptedAction 与注册

**Files:**
- Modify: `backend/forgemind/schema/decisions.py`
- Modify: `backend/forgemind/schema/actions.py`
- Modify: `backend/forgemind/runtime/acceptance.py`
- Modify: `backend/forgemind/state/action_registry.py`
- Create: `tests/test_search_code_action_flow.py`

**Interfaces:**
- Consumes: `SearchCodeArguments`。
- Produces: `SearchCodeToolCallDecision`、`AcceptedSearchCodeToolAction`、`accept_and_register_search_code_decision`。

- [ ] **Step 1: 写失败测试**

```python
def test_runtime_accepts_and_registers_search_decision() -> None:
    decision = SearchCodeToolCallDecision(
        action_type="tool_call",
        tool_name="search_code",
        arguments={"query": "discount"},
        reason="定位折扣逻辑",
    )
    registry = InMemoryActionRegistry()
    accepted = accept_and_register_search_code_decision(
        decision,
        task_id="task-001",
        registry=registry,
        next_action_id=lambda: "action-search-001",
    )
    assert accepted.arguments is decision.arguments
    assert registry.get("action-search-001") is accepted
```

另写测试给 Decision 传 `action_id` 并断言 `ValidationError`；预先注册相同 ID 后让生成器依次返回重复值和新值，断言最终登记新 ID。

- [ ] **Step 2: 运行 RED 测试**

Run: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-action tests\test_search_code_action_flow.py`

Expected: FAIL，因为 search_code Decision、Action 和接受函数尚不存在。

- [ ] **Step 3: 实现路由模型和接受入口**

```python
class SearchCodeToolCallDecision(StrictContractModel):
    action_type: Literal["tool_call"]
    tool_name: Literal["search_code"]
    arguments: SearchCodeArguments
    reason: str = Field(min_length=1)


class AcceptedSearchCodeToolAction(StrictContractModel):
    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_type: Literal["tool_call"]
    tool_name: Literal["search_code"]
    arguments: SearchCodeArguments
    reason: str = Field(min_length=1)
```

将 Action Registry 的值类型扩展为 read_file/search_code 的联合类型，保留唯一 ID 和不覆盖规则。

```python
AcceptedToolAction = AcceptedReadFileToolAction | AcceptedSearchCodeToolAction


def accept_search_code_decision(
    decision: SearchCodeToolCallDecision,
    *,
    task_id: str,
    next_action_id: ActionIdFactory = new_action_id,
) -> AcceptedSearchCodeToolAction:
    return AcceptedSearchCodeToolAction(
        action_id=next_action_id(),
        task_id=task_id,
        action_type=decision.action_type,
        tool_name=decision.tool_name,
        arguments=decision.arguments,
        reason=decision.reason,
    )
```

注册函数使用与 read_file 相同的最多三次 ID 冲突重试，但调用 `accept_search_code_decision`。

- [ ] **Step 4: 运行聚焦与完整测试**

Run focused: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-action tests\test_search_code_action_flow.py`

Run full: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\full-suite`

- [ ] **Step 5: 提交检查点**

`git commit -m "feat: accept and register search code actions"`

### Task 4: 安全搜索范围解析

**Files:**
- Create: `backend/forgemind/runtime/search_scope.py`
- Create: `tests/test_search_scope_resolution.py`

**Interfaces:**
- Consumes: `resolve_project_path(project_root: Path, requested_path: str) -> Path`。
- Produces: `resolve_search_scope(project_root: Path, requested_scope: str) -> Path`、`UnsupportedSearchScopeError`。

- [ ] **Step 1: 写失败测试**

```python
def test_resolve_search_scope_accepts_project_python_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    assert resolve_search_scope(root, "src/app.py") == target.resolve()


def test_resolve_search_scope_rejects_non_python_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "README.md"
    root.mkdir()
    target.write_text("text", encoding="utf-8")
    with pytest.raises(UnsupportedSearchScopeError):
        resolve_search_scope(root, "README.md")
```

另写目录成功、`../outside` 和绝对路径用例；后两者断言既有 `UnsafeProjectPathError`。

- [ ] **Step 2: 运行 RED 测试**

Run: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-scope tests\test_search_scope_resolution.py`

Expected: FAIL，因为 `resolve_search_scope` 尚不存在。

- [ ] **Step 3: 实现范围解析**

```python
def resolve_search_scope(project_root: Path, requested_scope: str) -> Path:
    resolved_scope = resolve_project_path(project_root, requested_scope)
    if resolved_scope.is_file() and resolved_scope.suffix != ".py":
        raise UnsupportedSearchScopeError(requested_scope)
    return resolved_scope
```

不存在的 scope 不在本步骤伪装成路径逃逸，留给 Tool 形成明确执行失败。

- [ ] **Step 4: 运行聚焦与完整测试**

Run focused: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-scope tests\test_search_scope_resolution.py`

Run full: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\full-suite`

- [ ] **Step 5: 提交检查点**

`git commit -m "feat: resolve safe search code scopes"`

### Task 5: 受限且确定的 Python 源码搜索

**Files:**
- Create: `backend/forgemind/tools/search_code.py`
- Create: `tests/test_search_code_tool.py`

**Interfaces:**
- Consumes: `SearchCodeArguments`、`SearchCodeMatch`、`SearchCodeResult` 和已经解析的 scope。
- Produces: `search_python_code(project_root: Path, resolved_scope: Path, arguments: SearchCodeArguments) -> SearchCodeResult`。

- [ ] **Step 1: 写失败测试**

```python
def test_search_python_code_returns_deterministic_matches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "b.py").parent.mkdir(parents=True)
    (root / "b.py").write_text("discount = 2\n", encoding="utf-8")
    (root / "a.py").write_text("x = 1\ndiscount = 1\n", encoding="utf-8")
    arguments = SearchCodeArguments(query="discount")
    result = search_python_code(root, root, arguments)
    assert [(m.path, m.line_number) for m in result.matches] == [
        ("a.py", 2),
        ("b.py", 1),
    ]
    assert result.is_complete is True
```

分别增加大小写不匹配、忽略目录、零匹配、三条命中但 max_results=2、65537 字节文件和非法 UTF-8 文件用例；后两种断言 `FILE_SKIPPED in incomplete_reasons`。

- [ ] **Step 2: 运行 RED 测试**

Run: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-tool tests\test_search_code_tool.py`

Expected: FAIL，因为 `search_python_code` 尚不存在。

- [ ] **Step 3: 实现候选收集和逐行搜索**

实现常量：

```python
MAX_SEARCH_FILE_BYTES = 64 * 1024
IGNORED_DIRECTORY_NAMES = frozenset(
    {".git", ".venv", "__pycache__", ".test-tmp"}
)
```

核心顺序：规范化 project_root；收集 `.py` 候选；排除忽略目录；按相对 POSIX 路径排序；逐个确认 resolve 后仍在根目录内；最多读取 65537 bytes；UTF-8 解码；使用 splitlines 逐行做 `query in line_text`；保存前 max_results 条，但扫描到第 max_results+1 条后立即标记 RESULT_LIMIT_REACHED。

- [ ] **Step 4: 运行聚焦与完整测试**

Run focused: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-tool tests\test_search_code_tool.py`

Run full: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\full-suite`

- [ ] **Step 5: 提交检查点**

`git commit -m "feat: search Python source with bounded resources"`

### Task 6: Observation 与统一 Runtime 执行入口

**Files:**
- Modify: `backend/forgemind/schema/observations.py`
- Create: `backend/forgemind/runtime/search_code_execution.py`
- Modify: `backend/forgemind/state/observation_registry.py`
- Create: `tests/test_search_code_execution_flow.py`
- Create: `tests/test_search_code_runtime_module_flow.py`
- Modify: `README.md`
- Modify: `docs/06-数据结构设计.md`
- Modify: `docs/16-项目开发日志.md`

**Interfaces:**
- Consumes: AcceptedSearchCodeToolAction、安全 scope 和 `search_python_code`。
- Produces: `SearchCodeSuccessObservation`、稳定 rejected/failed Observation，以及 `execute_search_code_action(...) -> TerminalObservation`。

稳定错误码固定为：项目外路径复用 `PATH_OUTSIDE_PROJECT`；非 `.py` 单文件使用 `UNSUPPORTED_SEARCH_SCOPE`；scope 不存在使用 `SEARCH_SCOPE_NOT_FOUND`；无法启动或完成根 scope 搜索使用 `SEARCH_FAILED`。候选文件被跳过属于成功结果中的 `FILE_SKIPPED`，不转成顶层 failed。

- [ ] **Step 1: 写执行流失败测试**

```python
def test_execute_search_code_records_success(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("discount = 1\n", encoding="utf-8")
    action, observations = make_registered_search_action(
        query="discount",
        scope=".",
    )
    observation = execute_search_code_action(
        action,
        project_root=root,
        observations=observations,
    )
    assert observation.status == "success"
    assert observation.result.returned_count == 1
    assert observations.get(action.action_id) is observation
```

另写零匹配 success、`../outside` rejected、`README.md` rejected 和不存在 scope failed 用例，每条均断言稳定错误码或 success result，并确认 Registry 中只有该终态。

- [ ] **Step 2: 运行 RED 测试**

Run: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-flow tests\test_search_code_execution_flow.py`

Expected: FAIL，因为 search_code Observation 和执行入口尚不存在。

- [ ] **Step 3: 实现 Observation 和执行顺序**

```text
安全范围解析失败 → rejected
scope 不存在或 Tool 无法搜索 → failed
搜索完成（包括零匹配或结果不完整）→ success
```

执行入口必须先登记 State，再向 Agent 返回同一个 Observation。

- [ ] **Step 4: 学习者编写模块级测试**

测试真实目录中多个 `.py` 文件的确定排序、返回上限、`is_complete` 和 State 对象身份。

- [ ] **Step 5: 运行聚焦与完整测试并归档**

Run focused: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\search-flow tests\test_search_code_execution_flow.py tests\test_search_code_runtime_module_flow.py`

Run full: `F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp\full-suite`

把真实测试数量和已完成边界追加到 `docs/06-数据结构设计.md` 与 `docs/16-项目开发日志.md`，并更新 README 当前进度。

- [ ] **Step 6: 提交检查点**

`git commit -m "feat: complete search code runtime flow"`
