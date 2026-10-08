"""浏览器上传项目后，经权限确认完成修复的公开 API 全流程。"""

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from forgemind.application import ForgeMindApplication
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.context import AgentTurnInput
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.workspaces import FileSystemWorkspaceStore


@dataclass
class SequenceModel:
    """按顺序返回固定 JSON，让测试只验证 Agent 外围的真实执行链。"""

    responses: list[str]

    def generate(self, turn_input: AgentTurnInput) -> str:
        return self.responses.pop(0)


def decision(**value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def read_sse(client: TestClient, task_id: str) -> tuple[str, list[dict[str, object]]]:
    """读取一段完整 SSE，并把每个公开事件解析为字典。"""

    with client.stream("GET", f"/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events: list[dict[str, object]] = []
    for block in filter(None, body.split("\n\n")):
        lines = block.splitlines()
        events.append(
            {
                "event": lines[0].removeprefix("event: "),
                "id": int(lines[1].removeprefix("id: ")),
                "payload": json.loads(lines[2].removeprefix("data: ")),
            }
        )
    return body, events


def test_uploaded_project_can_be_edited_verified_and_completed_over_web(
    tmp_path: Path,
) -> None:
    # 1. 准备：模型依次要求检索、读取、修改、测试，证据完整后才完成。
    before = b"def discount():\n    return 1\n"
    after = b"def discount():\n    return 2\n"
    test_source = (
        b"import pricing\n\n"
        b"def test_discount():\n"
        b"    assert pricing.discount() == 2\n"
    )
    model = SequenceModel(
        [
            decision(
                action_type="tool_call",
                tool_name="search_code",
                arguments={"query": "discount", "scope": "."},
                # 模拟模型意外回显服务器路径，公开协议必须统一脱敏。
                reason="先定位折扣实现与测试：__SERVER_WORKSPACE_ROOT__",
            ),
            decision(
                action_type="tool_call",
                tool_name="read_file",
                arguments={"path": "pricing.py"},
                reason="读取修改前的完整实现",
            ),
            decision(
                action_type="tool_call",
                tool_name="edit_file",
                arguments={
                    "path": "pricing.py",
                    "old_text": "return 1",
                    "new_text": "return 2",
                    "expected_version": calculate_content_version(before),
                },
                reason="把错误的折扣返回值改为 2",
            ),
            decision(
                action_type="tool_call",
                tool_name="run_tests",
                arguments={
                    "targets": ["test_pricing.py"],
                    "timeout_seconds": 30,
                },
                reason="用项目测试验证修改后的真实行为",
            ),
            decision(
                action_type="complete",
                reason="修改成功且真实测试已经通过",
                summary="折扣返回值已修复，test_pricing.py 已通过。",
            ),
        ]
    )
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    application = ForgeMindApplication(state=state, model=model)
    workspace_store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    client = TestClient(create_agent_stream_app(application, workspace_store))

    # 2. 上传：浏览器发送文件内容，服务端返回公开 workspace_id。
    upload_response = client.post(
        "/workspaces",
        files=[
            ("files", ("pricing.py", before, "text/x-python")),
            ("files", ("test_pricing.py", test_source, "text/x-python")),
        ],
    )
    print("上传响应：", upload_response.status_code, upload_response.json())
    assert upload_response.status_code == 201
    workspace_id = upload_response.json()["workspace_id"]
    workspace_root = workspace_store.resolve(workspace_id)
    escaped_workspace_root = json.dumps(
        str(workspace_root),
        ensure_ascii=False,
    )[1:-1]
    model.responses = [
        response.replace("__SERVER_WORKSPACE_ROOT__", escaped_workspace_root)
        for response in model.responses
    ]

    # 3. 创建任务：公开请求只引用 workspace_id，不接收或泄露绝对路径。
    create_response = client.post(
        "/tasks",
        json={
            "original_request": "把 discount 返回值修复为 2，并运行测试。",
            "workspace_id": workspace_id,
        },
    )
    print("创建任务响应：", create_response.status_code, create_response.json())
    assert create_response.status_code == 201
    task_id = create_response.json()["task_id"]
    assert "project_root" not in create_response.text

    # 4. 第一段 SSE：修改被 Runtime 暂停，文件此时仍保持原样。
    first_body, first_events = read_sse(client, task_id)
    print("第一次 SSE（等待修改权限）：\n", first_body)
    assert [event["event"] for event in first_events] == [
        "agent.step",
        "agent.step",
        "agent.step",
        "task.permission_required",
    ]
    assert (workspace_root / "pricing.py").read_bytes() == before
    edit_payload = first_events[-1]["payload"]
    assert isinstance(edit_payload, dict)
    edit_permission_id = edit_payload["data"]["permission_request_id"]

    # 5. 批准精确修改：POST 返回最新公开 State，磁盘内容才发生变化。
    edit_response = client.post(
        f"/tasks/{task_id}/permissions/{edit_permission_id}",
        json={"decision": "approve", "raw_response": "同意这次精确修改"},
    )
    print("批准修改响应：", edit_response.status_code, edit_response.json())
    assert edit_response.status_code == 200
    assert edit_response.json()["status"] == "running"
    assert edit_response.json()["actions"][-1]["observation"]["status"] == "success"
    assert (workspace_root / "pricing.py").read_bytes() == after

    # 6. 第二段 SSE：运行测试也是受保护动作，必须再次独立授权。
    second_body, second_events = read_sse(client, task_id)
    print("第二次 SSE（等待测试权限）：\n", second_body)
    assert [event["event"] for event in second_events] == [
        "agent.step",
        "task.permission_required",
    ]
    test_payload = second_events[-1]["payload"]
    assert isinstance(test_payload, dict)
    test_permission_id = test_payload["data"]["permission_request_id"]

    test_response = client.post(
        f"/tasks/{task_id}/permissions/{test_permission_id}",
        json={"decision": "approve", "raw_response": "同意运行指定测试"},
    )
    print("批准测试响应：", test_response.status_code, test_response.json())
    assert test_response.status_code == 200
    test_observation = test_response.json()["actions"][-1]["observation"]
    assert test_observation["status"] == "success"
    assert test_observation["result"]["test_outcome"] == "passed"

    # 7. 第三段 SSE：模型读到真实测试证据后完成，GET 可恢复完整终态。
    third_body, third_events = read_sse(client, task_id)
    print("第三次 SSE（任务完成）：\n", third_body)
    assert [event["event"] for event in third_events] == [
        "agent.step",
        "task.completed",
    ]
    completed_payload = third_events[-1]["payload"]
    assert isinstance(completed_payload, dict)
    assert completed_payload["data"]["summary"] == (
        "折扣返回值已修复，test_pricing.py 已通过。"
    )

    restored = client.get(f"/tasks/{task_id}")
    print("刷新后恢复的任务状态：", restored.json())
    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"
    assert len(restored.json()["actions"]) == 5

    # 所有公开响应均不得包含服务端真实工作区路径。
    public_text = "".join(
        [
            upload_response.text,
            create_response.text,
            first_body,
            edit_response.text,
            second_body,
            test_response.text,
            third_body,
            restored.text,
        ]
    )
    assert str(workspace_root) not in public_text
    assert str(workspace_root).replace("\\", "\\\\") not in public_text
    assert "forgemind-run-tests-" not in public_text
    assert "<forgemind-temp>" in public_text
