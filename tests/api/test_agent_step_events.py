"""观察 Agent 单轮结果如何转换为公开流式事件。"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forgemind.agent.loop import AgentLoopStepResult
from forgemind.agent.turn import AgentTurnResult
from forgemind.application import ForgeMindApplication
from forgemind.runtime.versioning import calculate_content_version
from forgemind.runtime.completion import CompletionResult
from forgemind.schema.actions import AcceptedCompletionAction
from forgemind.schema.context import AgentInputMessage, AgentTurnInput
from forgemind.schema.decisions import CompleteTaskDecision
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_events import (
    build_agent_step_event,
    generate_agent_step_events,
)
from forgemind.web.agent_api import create_agent_stream_app


@dataclass
class SequenceModel:
    """测试模型：每调用一次，就按顺序返回一条预设响应。"""

    responses: list[str]
    received_inputs: list[object] = field(default_factory=list)

    def generate(self, turn_input: object) -> str:
        self.received_inputs.append(turn_input)
        return self.responses.pop(0)


def test_build_agent_step_event_exposes_structured_result() -> None:
    """公开事件应包含已解析 Decision 和 Runtime 结果。"""

    # 第一步（准备数据）：构造模型已经成功解析出的完成 Decision。
    decision = CompleteTaskDecision(
        action_type="complete",
        reason="已有充分证据",
        summary="任务已经完成",
    )
    turn_result = AgentTurnResult(
        turn_input=AgentTurnInput(
            messages=(
                AgentInputMessage(role="system", content="系统规则"),
                AgentInputMessage(role="user", content="任务上下文"),
            )
        ),
        raw_response='{"这里是":"模型原始文本"}',
        decision_result=decision,
    )

    # 第二步（准备数据）：构造 Runtime 接受 Decision 后保存的权威结果。
    runtime_result = CompletionResult(
        action=AcceptedCompletionAction(
            action_id="action-001",
            task_id="task-001",
            action_type="complete",
            reason=decision.reason,
            summary=decision.summary,
        ),
        completed_status=TaskStatusRecord(
            task_status_id="status-002",
            task_id="task-001",
            revision=2,
            status=TaskStatus.COMPLETED,
            reason=decision.summary,
        ),
    )
    step = AgentLoopStepResult(
        turn_result=turn_result,
        dispatch_result=runtime_result,
    )

    # 第三步（执行动作）：把内部的一轮结果映射成公开事件。
    event = build_agent_step_event(
        task_id="task-001",
        sequence=7,
        step_number=1,
        step=step,
    )

    # 第四步（观察结果）：打印客户端以后真正能收到的结构。
    print("agent.step 公开事件：", event.model_dump(mode="json"))

    # 第五步（检查结果）：事件序号和 Agent 轮数保持各自含义。
    assert event.event == "agent.step"
    assert event.sequence == 7
    assert event.task_id == "task-001"
    assert event.data["step_number"] == 1

    # 第六步（检查边界）：公开结构来自严格解析和 Runtime，不含模型原文。
    assert event.data["decision"] == decision.model_dump(mode="json")
    assert event.data["runtime"]["action"]["action_id"] == "action-001"
    assert event.data["runtime"]["completed_status"]["status"] == "completed"
    assert "raw_response" not in event.data


def test_generate_agent_step_events_drives_one_real_step_per_next(
    tmp_path: Path,
) -> None:
    """每次 next() 应只驱动一轮真实 Application 执行。"""

    # 第一步（准备项目）：search_code 需要一个可以真实找到的 Python 文件。
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    model = SequenceModel(
        responses=[
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "search_code",
                    "arguments": {"query": "value", "scope": "."},
                    "reason": "先查找代码",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "action_type": "complete",
                    "reason": "已经取得证据",
                    "summary": "查找完成",
                },
                ensure_ascii=False,
            ),
        ]
    )
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=model,
    )
    task = application.create_task(
        "查找 value",
        tmp_path,
        next_task_id=lambda: "task-001",
        next_task_status_id=lambda: "status-001",
    )

    # 第二步（准备生成器）：创建生成器不会立即调用模型。
    events = generate_agent_step_events(
        application,
        task.task_id,
        max_steps=5,
        first_sequence=10,
    )
    print("创建生成器后的模型调用次数：", len(model.received_inputs))
    assert len(model.received_inputs) == 0

    # 第三步（执行第一轮）：第一次 next() 只完成 search_code 这一轮。
    first = next(events)
    print("第一条真实 Agent 事件：", first.model_dump(mode="json"))
    print("第一轮后的模型调用次数：", len(model.received_inputs))
    assert first.sequence == 10
    assert first.data["step_number"] == 1
    assert first.data["decision"]["tool_name"] == "search_code"
    assert len(model.received_inputs) == 1

    # 第四步（执行第二轮）：第二次 next() 才调用模型并完成任务。
    second = next(events)
    print("第二条真实 Agent 事件：", second.model_dump(mode="json"))
    print("第二轮后的模型调用次数：", len(model.received_inputs))
    assert second.sequence == 11
    assert second.data["step_number"] == 2
    assert second.data["decision"]["action_type"] == "complete"
    assert len(model.received_inputs) == 2

    # 第五步（读取终态）：完成步骤后再发一条专用终态事件。
    completed = next(events)
    assert completed.event == "task.completed"
    assert completed.sequence == 12
    assert completed.data["summary"] == "查找完成"

    # 第六步（检查停止）：任务完成后，生成器不能继续调用模型。
    with pytest.raises(StopIteration):
        next(events)
    assert application.get_task(task.task_id).current_status.status is TaskStatus.COMPLETED
    assert len(model.received_inputs) == 2


def test_agent_stream_route_sends_real_steps_as_sse(tmp_path: Path) -> None:
    """FastAPI 路由应把真实 Agent 步骤编码成有序 SSE 事件。"""

    # 第一步（准备项目和模型）：第一轮查找代码，第二轮完成任务。
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    model = SequenceModel(
        responses=[
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "search_code",
                    "arguments": {"query": "value", "scope": "."},
                    "reason": "先查找代码",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "action_type": "complete",
                    "reason": "已经取得证据",
                    "summary": "查找完成",
                },
                ensure_ascii=False,
            ),
        ]
    )
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=model,
    )
    task = application.create_task(
        "查找 value",
        tmp_path,
        next_task_id=lambda: "task-001",
        next_task_status_id=lambda: "status-001",
    )

    # 第二步（准备 Web 层）：把已经配置好的 Application 注入应用工厂。
    web_app = create_agent_stream_app(application)
    client = TestClient(web_app)

    # 第三步（执行动作）：通过真实 HTTP 测试接口读取完整 SSE 响应。
    with client.stream(
        "GET",
        f"/tasks/{task.task_id}/events?max_steps=5",
    ) as response:
        body = "".join(response.iter_text())

    # 第四步（观察结果）：打印响应头和客户端实际收到的协议文本。
    print("Agent SSE 响应状态：", response.status_code)
    print("Agent SSE Content-Type：", response.headers["content-type"])
    print("Agent SSE 完整正文：\n", body)

    # 第五步（解析协议）：空行分开事件，每条 data 行再解析成 JSON。
    blocks = [block for block in body.split("\n\n") if block]
    first_lines = blocks[0].splitlines()
    second_lines = blocks[1].splitlines()
    completed_lines = blocks[2].splitlines()
    first_data = json.loads(first_lines[2].removeprefix("data: "))
    second_data = json.loads(second_lines[2].removeprefix("data: "))

    # 第六步（检查结果）：两轮按顺序到达，且来自同一个真实任务。
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(blocks) == 3
    assert first_lines[:2] == ["event: agent.step", "id: 1"]
    assert second_lines[:2] == ["event: agent.step", "id: 2"]
    assert completed_lines[:2] == ["event: task.completed", "id: 3"]
    assert first_data["task_id"] == "task-001"
    assert first_data["data"]["decision"]["tool_name"] == "search_code"
    assert second_data["data"]["decision"]["action_type"] == "complete"


def test_edit_permission_step_emits_permission_required_event(
    tmp_path: Path,
) -> None:
    before = b"value = 1\n"
    (tmp_path / "main.py").write_bytes(before)
    model = SequenceModel(
        responses=[
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "edit_file",
                    "arguments": {
                        "path": "main.py",
                        "old_text": "value = 1",
                        "new_text": "value = 2",
                        "expected_version": calculate_content_version(before),
                    },
                    "reason": "修改目标值",
                },
                ensure_ascii=False,
            )
        ]
    )
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"), model=model
    )
    task = application.create_task("修改 value", tmp_path)

    events = list(generate_agent_step_events(application, task.task_id))

    assert [event.event for event in events] == [
        "agent.step",
        "task.permission_required",
    ]
    permission = events[1]
    stored_request = application.get_task(task.task_id).actions[-1].permission_request
    assert stored_request is not None
    assert permission.data["permission_request_id"] == (
        stored_request.permission_request_id
    )
    assert permission.data["tool_name"] == "edit_file"
    assert permission.data["arguments"]["path"] == "main.py"
    assert str(tmp_path.resolve()) not in json.dumps(permission.data)


def test_execution_exception_is_converted_to_public_failed_event() -> None:
    class ExplodingApplication:
        def run_until_pause(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("secret server path: C:/private")

    events = list(
        generate_agent_step_events(  # type: ignore[arg-type]
            ExplodingApplication(),
            "task-001",
            first_sequence=4,
        )
    )

    assert len(events) == 1
    assert events[0].event == "task.failed"
    assert events[0].sequence == 4
    assert events[0].data == {
        "category": "internal_error",
        "message": "任务执行失败，请查看服务端日志。",
    }
    assert "private" not in json.dumps(events[0].data)


def test_ask_user_step_emits_waiting_event_and_ends_stream(
    tmp_path: Path,
) -> None:
    """Agent 提问后应发出等待事件，并结束本次流。"""

    # 第一步（准备模型）：让模型只提出一个有选项的问题。
    model = SequenceModel(
        responses=[
            json.dumps(
                {
                    "action_type": "ask_user",
                    "reason": "缺少数据库选择",
                    "question": "请选择 SQLite 或 PostgreSQL。",
                    "options": ["SQLite", "PostgreSQL"],
                },
                ensure_ascii=False,
            )
        ]
    )

    # 第二步（准备真实任务）：使用临时 SQLite 保存 WAITING_USER 状态。
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=model,
    )
    task = application.create_task(
        "根据选择配置数据库",
        tmp_path,
        next_task_id=lambda: "task-waiting-001",
        next_task_status_id=lambda: "status-running-001",
    )
    client = TestClient(create_agent_stream_app(application))

    # 第三步（执行动作）：读取本次任务流，直到服务端结束响应。
    with client.stream(
        "GET",
        f"/tasks/{task.task_id}/events?max_steps=5",
    ) as response:
        body = "".join(response.iter_text())

    # 第四步（观察结果）：打印事件文本和权威任务状态。
    print("等待用户时的 HTTP 状态：", response.status_code)
    print("等待用户时的 SSE 正文：\n", body)
    print("当前任务状态：", application.get_task(task.task_id).current_status.status)

    # 第五步（解析协议）：空行分开事件，data 行中的 JSON 再单独解析。
    blocks = [block for block in body.split("\n\n") if block]
    first_lines = blocks[0].splitlines()
    waiting_lines = blocks[1].splitlines()
    waiting_data = json.loads(waiting_lines[2].removeprefix("data: "))
    task_view = application.get_task(task.task_id)

    # 第六步（检查结果）：先检查 HTTP 和事件顺序，保证等待事件没有丢失。
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(blocks) == 2
    assert first_lines[:2] == ["event: agent.step", "id: 1"]
    assert waiting_lines[:2] == ["event: task.waiting_user", "id: 2"]

    # 第七步（检查业务事实）：问题、选项和 action_id 必须对应 State 中的记录。
    assert waiting_data["task_id"] == task.task_id
    assert waiting_data["data"]["question_action_id"] == (
        task_view.actions[0].action.action_id
    )
    assert waiting_data["data"]["question"] == "请选择 SQLite 或 PostgreSQL。"
    assert waiting_data["data"]["options"] == ["SQLite", "PostgreSQL"]
    assert task_view.current_status.status is TaskStatus.WAITING_USER
    assert len(model.received_inputs) == 1


def test_answer_post_persists_user_response_and_reconnected_stream_resumes(
    tmp_path: Path,
) -> None:
    """POST 回答应先持久化，再由新的 SSE 请求继续调用 Agent。"""

    # 第一步（准备模型）：第一轮提出问题，收到回答后第二轮完成任务。
    model = SequenceModel(
        responses=[
            json.dumps(
                {
                    "action_type": "ask_user",
                    "reason": "需要用户选择数据库",
                    "question": "请选择数据库。",
                    "options": ["SQLite", "PostgreSQL"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "action_type": "complete",
                    "reason": "用户已选择数据库",
                    "summary": "已按用户选择完成配置",
                },
                ensure_ascii=False,
            ),
        ]
    )
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=model,
    )
    task = application.create_task(
        "根据用户选择配置数据库",
        tmp_path,
        next_task_id=lambda: "task-answer-001",
        next_task_status_id=lambda: "status-running-001",
    )
    client = TestClient(create_agent_stream_app(application))

    # 第二步（读取等待事件）：GET 运行第一轮，并从事件中取回原问题 ID。
    with client.stream("GET", f"/tasks/{task.task_id}/events") as response:
        first_body = "".join(response.iter_text())
    first_blocks = [block for block in first_body.split("\n\n") if block]
    waiting_lines = first_blocks[1].splitlines()
    waiting_payload = json.loads(waiting_lines[2].removeprefix("data: "))
    question_action_id = waiting_payload["data"]["question_action_id"]
    print("第一段 SSE 等待事件：\n", first_blocks[1])

    # 第三步（提交回答）：浏览器把原问题 ID 和用户选择一起 POST。
    answer_response = client.post(
        f"/tasks/{task.task_id}/answers",
        json={
            "question_action_id": question_action_id,
            "raw_response": "我选择 PostgreSQL，因为需要多用户并发。",
            "selected_option": "PostgreSQL",
        },
    )
    print("回答 POST 状态：", answer_response.status_code)
    print("回答 POST 返回：", answer_response.json())
    assert answer_response.status_code == 200
    saved_task = application.get_task(task.task_id)
    print("POST 后的权威任务状态：", saved_task.current_status.status.value)
    print("SQLite 中保存的用户原话：", saved_task.actions[0].user_response.raw_response)

    # 第四步（重新连接）：只有新 GET 才会再驱动 Agent，读取刚保存的回答。
    with client.stream("GET", f"/tasks/{task.task_id}/events") as response:
        resumed_body = "".join(response.iter_text())
    resumed_blocks = [block for block in resumed_body.split("\n\n") if block]
    resumed_payload = json.loads(
        resumed_blocks[0].splitlines()[2].removeprefix("data: ")
    )
    print("重新连接后收到的 SSE：\n", resumed_body)
    print("模型调用次数：", len(model.received_inputs))

    # 第五步（检查完整因果链）：响应已保存、上下文带入回答、任务完成。
    assert response.status_code == 200
    assert answer_response.status_code == 200
    answer_data = answer_response.json()
    assert answer_data["task_id"] == task.task_id
    assert answer_data["question_action_id"] == question_action_id
    assert answer_data["status"] == "running"
    assert answer_data["revision"] == 3
    assert saved_task.current_status.status is TaskStatus.RUNNING
    assert saved_task.actions[0].user_response.raw_response == (
        "我选择 PostgreSQL，因为需要多用户并发。"
    )
    assert saved_task.actions[0].user_response.selected_option == "PostgreSQL"
    assert len(model.received_inputs) == 2
    assert "PostgreSQL" in model.received_inputs[1].messages[1].content
    assert resumed_payload["data"]["decision"]["action_type"] == "complete"
    assert application.get_task(task.task_id).current_status.status is TaskStatus.COMPLETED


def test_answer_post_rejects_unknown_question_id_without_changing_waiting_state(
    tmp_path: Path,
) -> None:
    """错误问题 ID 不能写入回答，也不能解除任务等待。"""

    # 第一步（准备等待任务）：模型提出问题后，本轮只有一次模型调用。
    model = SequenceModel(
        responses=[
            json.dumps(
                {
                    "action_type": "ask_user",
                    "reason": "需要用户选择",
                    "question": "请选择一个数据库。",
                    "options": ["SQLite", "PostgreSQL"],
                },
                ensure_ascii=False,
            )
        ]
    )
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=model,
    )
    task = application.create_task(
        "按用户选择配置数据库",
        tmp_path,
        next_task_id=lambda: "task-wrong-question-001",
        next_task_status_id=lambda: "status-running-001",
    )
    client = TestClient(create_agent_stream_app(application))

    # 第二步（进入等待）：先运行 SSE，确保 Action 已真实写入 State。
    with client.stream("GET", f"/tasks/{task.task_id}/events") as response:
        waiting_body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: task.waiting_user" in waiting_body

    # 第三步（提交错误 ID）：该编号没有对应的 AskUserAction。
    answer_response = client.post(
        f"/tasks/{task.task_id}/answers",
        json={
            "question_action_id": "question-that-does-not-exist",
            "raw_response": "SQLite",
            "selected_option": "SQLite",
        },
    )
    task_view = application.get_task(task.task_id)
    print("错误问题 ID 的 HTTP 响应：", answer_response.status_code)
    print("错误问题 ID 的说明：", answer_response.json())
    print("回答后任务状态：", task_view.current_status.status.value)
    print("问题记录中的用户回答：", task_view.actions[0].user_response)

    # 第四步（检查拒绝事实）：没有回答被保存，状态继续等待原问题。
    assert answer_response.status_code == 404
    assert task_view.current_status.status is TaskStatus.WAITING_USER
    assert task_view.actions[0].user_response is None
