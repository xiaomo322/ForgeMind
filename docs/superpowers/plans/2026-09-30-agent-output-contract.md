# Agent Output Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从现有 `AgentDecision` 自动生成模型输出协议，并将它加入每轮 Agent 的 system 消息。

**Architecture:** `schema.decisions.AgentDecision` 继续作为唯一字段事实来源。`context.messages` 使用 Pydantic `TypeAdapter.json_schema()` 生成确定性的 JSON Schema 文本，再把固定输出规则和 Schema 拼入 system 消息；现有 Parser 仍负责最终校验。

**Tech Stack:** Python 3.11+、Pydantic 2.10.3、pytest 8.3.4

## Global Constraints

- 模型只能输出一个 JSON 对象，不得输出 Markdown 代码块或额外解释。
- 模型不得生成 `action_id`；Runtime 接受 Decision 后负责分配。
- 协议必须覆盖 `ask_user` 和五个现有 Tool Decision，且不得维护第二套手写字段定义。
- 本切片不接入真实模型 SDK，不修改 State、Parser 或 Runtime 执行流程。

---

### Task 1: 生成供应商无关的 Decision 输出协议

**Files:**
- Modify: `backend/forgemind/context/messages.py`
- Create: `tests/test_agent_output_contract.py`

**Interfaces:**
- Consumes: `forgemind.schema.decisions.AgentDecision`
- Produces: `build_agent_decision_output_contract() -> str`、`AGENT_DECISION_SCHEMA_START`、`AGENT_DECISION_SCHEMA_END`

- [x] **Step 1: 写协议行为测试**

```python
import json

from pydantic import TypeAdapter

from forgemind.context.messages import (
    AGENT_DECISION_SCHEMA_END,
    AGENT_DECISION_SCHEMA_START,
    build_agent_decision_output_contract,
)
from forgemind.schema.decisions import AgentDecision


def test_output_contract_contains_exact_agent_decision_schema() -> None:
    contract = build_agent_decision_output_contract()
    schema_text = contract.split(
        AGENT_DECISION_SCHEMA_START + "\n", maxsplit=1
    )[1].split("\n" + AGENT_DECISION_SCHEMA_END, maxsplit=1)[0]

    assert json.loads(schema_text) == TypeAdapter(
        AgentDecision
    ).json_schema()


def test_output_contract_states_non_negotiable_output_rules() -> None:
    contract = build_agent_decision_output_contract()

    assert "只返回一个" in contract
    assert "JSON" in contract
    assert "Markdown" in contract
    assert "action_id" in contract
    assert "Runtime" in contract
```

- [x] **Step 2: 运行测试并确认先失败**

Run:

```powershell
F:\anaconda3\python.exe -m pytest tests\test_agent_output_contract.py -q -p no:cacheprovider --basetemp=tests\.tmp-agent-output-red
```

Expected: 测试收集阶段因三个新接口尚不存在而失败。

- [x] **Step 3: 在 messages.py 加入导入、适配器和中文步骤注释骨架**

```python
import json

from pydantic import TypeAdapter

from forgemind.schema.decisions import AgentDecision


_AGENT_DECISION_ADAPTER = TypeAdapter(AgentDecision)
AGENT_DECISION_SCHEMA_START = "<agent_decision_json_schema>"
AGENT_DECISION_SCHEMA_END = "</agent_decision_json_schema>"


def build_agent_decision_output_contract() -> str:
    """生成与严格 AgentDecision 契约同步的模型输出说明。"""

    # 第一步：调用 _AGENT_DECISION_ADAPTER.json_schema() 取得 Python 字典。
    # 第二步：使用 json.dumps 把字典序列化为确定的紧凑 JSON 文本；保留中文。
    # 第三步：返回行为规则、开始标记、Schema 文本和结束标记组成的字符串。
    raise NotImplementedError("请完成 Agent 输出协议生成")
```

- [x] **Step 4: 由学习者完成核心函数**

目标实现：

```python
def build_agent_decision_output_contract() -> str:
    """生成与严格 AgentDecision 契约同步的模型输出说明。"""

    schema_json = json.dumps(
        _AGENT_DECISION_ADAPTER.json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "你必须只返回一个符合下方 JSON Schema 的 JSON 对象。\n"
        "不要使用 Markdown 代码块，不要添加 JSON 之外的解释文字。\n"
        "不要生成 action_id；Runtime 会在接受 Decision 后分配。\n"
        f"{AGENT_DECISION_SCHEMA_START}\n"
        f"{schema_json}\n"
        f"{AGENT_DECISION_SCHEMA_END}"
    )
```

- [x] **Step 5: 运行协议测试并确认通过**

Run: 与 Step 2 相同。

Expected: `2 passed`。

---

### Task 2: 把输出协议接入 Agent system 消息

**Files:**
- Modify: `backend/forgemind/context/messages.py`
- Modify: `tests/test_agent_context_messages.py`
- Test: `tests/test_agent_turn.py`

**Interfaces:**
- Consumes: `build_agent_decision_output_contract() -> str`
- Produces: 包含固定安全规则和完整输出协议的 `FORGEMIND_SYSTEM_INSTRUCTIONS`

- [x] **Step 1: 扩展 system 消息测试**

在 `test_turn_input_separates_system_rules_from_context_data` 中加入：

```python
    assert AGENT_DECISION_SCHEMA_START in system_message.content
    assert AGENT_DECISION_SCHEMA_END in system_message.content
    assert "不要生成 action_id" in system_message.content
    assert AGENT_DECISION_SCHEMA_START not in user_message.content
```

并从 `forgemind.context.messages` 导入两个 Schema 标记常量。

- [x] **Step 2: 运行测试并确认先失败**

Run:

```powershell
F:\anaconda3\python.exe -m pytest tests\test_agent_context_messages.py -q -p no:cacheprovider --basetemp=tests\.tmp-agent-output-integration-red
```

Expected: system 消息尚未包含 Schema 标记，断言失败。

- [x] **Step 3: 把协议追加到固定 system 指令**

先把现有安全规则改名为 `_FORGEMIND_BASE_SYSTEM_INSTRUCTIONS`，然后构造公开常量：

```python
FORGEMIND_SYSTEM_INSTRUCTIONS = (
    _FORGEMIND_BASE_SYSTEM_INSTRUCTIONS.rstrip()
    + "\n\n"
    + build_agent_decision_output_contract()
    + "\n"
)
```

`build_agent_turn_input()` 继续使用 `FORGEMIND_SYSTEM_INSTRUCTIONS`，无需修改消息顺序或 user Context。

- [x] **Step 4: 运行输出协议与 Agent 相关测试**

Run:

```powershell
F:\anaconda3\python.exe -m pytest tests\test_agent_output_contract.py tests\test_agent_context_messages.py tests\test_agent_turn.py tests\test_agent_loop_step.py -q -p no:cacheprovider --basetemp=tests\.tmp-agent-output-focused
```

Expected: `11 passed`。

- [x] **Step 5: 运行完整回归**

Run:

```powershell
F:\anaconda3\python.exe -m pytest -q -p no:cacheprovider --basetemp=tests\.tmp-agent-output-full
```

Expected: 现有 532 项加本切片 2 项，共 `534 passed`。

- [x] **Step 6: 更新进度并提交**

更新 `README.md`、`docs/06-数据结构设计.md` 和 `docs/16-项目开发日志.md`，只记录已实现行为与真实测试数字。

```powershell
git add backend/forgemind/context/messages.py tests/test_agent_output_contract.py tests/test_agent_context_messages.py README.md docs/06-数据结构设计.md docs/16-项目开发日志.md
git commit -m "feat: define agent model output contract"
```
