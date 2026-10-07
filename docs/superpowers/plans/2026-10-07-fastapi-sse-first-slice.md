# FastAPI SSE First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个可独立运行和测试的 FastAPI SSE 学习端点，让客户端通过同一个 HTTP 响应依次收到三条事件。

**Architecture:** 在 `forgemind.web` 下创建独立学习模块。同步生成器负责逐块 `yield` SSE 文本，FastAPI `StreamingResponse` 负责把每块内容写入 HTTP 响应；测试通过 `TestClient.stream()` 读取真实响应。该切片不连接模型、SQLite 或 Runtime。

**Tech Stack:** Python 3.11、FastAPI、Starlette `StreamingResponse`、FastAPI `TestClient`、pytest

## Global Constraints

- 每次只引入一个主要概念，第一切片只学习生成器、`StreamingResponse` 和 SSE 分隔符。
- 核心代码包含说明设计原因的中文注释。
- 用户可以选择亲手输入核心函数，也可以由 AI 补齐后逐行讲解。
- 不修改现有 `tests/FastAPI学习` 文件，避免与尚未完成的 PATCH 练习互相影响。
- 不连接真实模型、SQLite、ForgeMind Runtime 或外部网络。
- 聚焦测试通过后才进入统一事件契约。

---

### Task 1: 三事件 SSE 学习端点

**Files:**
- Create: `backend/forgemind/web/__init__.py`
- Create: `backend/forgemind/web/learning_sse.py`
- Create: `tests/test_learning_sse.py`

**Interfaces:**
- Consumes: FastAPI `FastAPI`、`StreamingResponse` 和 `TestClient.stream()`。
- Produces: `generate_demo_events() -> Iterator[str]` 和 FastAPI 路由 `GET /learning/sse`。

- [ ] **Step 1: 建立失败测试，描述客户端可观察行为**

创建 `tests/test_learning_sse.py`：

```python
from fastapi.testclient import TestClient

from forgemind.web.learning_sse import app


client = TestClient(app)


def test_learning_sse_returns_three_complete_events() -> None:
    with client.stream("GET", "/learning/sse") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert body == (
        "event: lesson\n"
        'data: {"step":1,"message":"任务开始"}\n\n'
        "event: lesson\n"
        'data: {"step":2,"message":"正在执行"}\n\n'
        "event: lesson\n"
        'data: {"step":3,"message":"任务完成"}\n\n'
    )
```

- [ ] **Step 2: 运行测试，确认它因为模块尚不存在而失败**

运行：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -q -p no:cacheprovider --basetemp=.test-tmp/sse-red tests/test_learning_sse.py
```

预期：测试收集失败并报告 `ModuleNotFoundError: No module named 'forgemind.web'`。

- [ ] **Step 3: 创建 Web 包和最小学习端点**

创建空文件 `backend/forgemind/web/__init__.py`。

创建 `backend/forgemind/web/learning_sse.py`：

```python
"""用于理解 FastAPI 与 SSE 数据流的最小示例。"""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse


app = FastAPI()


def generate_demo_events() -> Iterator[str]:
    """逐次产出三条完整 SSE 事件。"""

    # yield 产出一块数据后暂停，并在下一次迭代时从这里继续。
    yield 'event: lesson\ndata: {"step":1,"message":"任务开始"}\n\n'
    yield 'event: lesson\ndata: {"step":2,"message":"正在执行"}\n\n'
    yield 'event: lesson\ndata: {"step":3,"message":"任务完成"}\n\n'


@app.get("/learning/sse")
def stream_lesson() -> StreamingResponse:
    """把生成器产生的每一块内容写入同一个 HTTP 响应。"""

    return StreamingResponse(
        generate_demo_events(),
        media_type="text/event-stream",
    )
```

- [ ] **Step 4: 运行聚焦测试，确认响应类型、顺序和空行全部正确**

运行：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -q -p no:cacheprovider --basetemp=.test-tmp/sse-green tests/test_learning_sse.py
```

预期：`1 passed`。

- [ ] **Step 5: 增加逐块观察测试，理解客户端 API**

在 `tests/test_learning_sse.py` 添加：

```python
def test_generator_pauses_and_keeps_its_position() -> None:
    events = generate_demo_events()

    first = next(events)
    second = next(events)

    assert "任务开始" in first
    assert "正在执行" in second
```

并在导入列表中加入：

```python
from forgemind.web.learning_sse import app, generate_demo_events
```

- [ ] **Step 6: 运行本切片测试并共同阅读输出**

运行：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -vv -s -p no:cacheprovider --basetemp=.test-tmp/sse-slice tests/test_learning_sse.py
```

预期：两个测试都通过。解释 `TestClient.stream()`、上下文管理器、`iter_text()`、`next()` 和响应头各自负责什么。

- [ ] **Step 7: 检查差异并提交单一切片**

```powershell
git diff --check -- backend/forgemind/web tests/test_learning_sse.py
git add -- backend/forgemind/web/__init__.py backend/forgemind/web/learning_sse.py tests/test_learning_sse.py
git commit -m "feat: add minimal FastAPI SSE learning endpoint"
```

提交前确认不包含现有 FastAPI 学习文件、`pyproject.toml`、`uv.lock`、计算器文件或 Agent Loop 的个人修改。
