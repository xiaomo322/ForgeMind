"""用户批准或拒绝 Tool 权限请求的 API 测试。"""

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from forgemind.application import ForgeMindApplication
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.context import AgentTurnInput
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.workspaces import FileSystemWorkspaceStore, WorkspaceUpload


@dataclass
class SequenceModel:
    responses: list[str]

    def generate(self, turn_input: AgentTurnInput) -> str:
        return self.responses.pop(0)


def prepare_edit_wait(
    tmp_path: Path,
) -> tuple[TestClient, ForgeMindApplication, Path, str, str]:
    before = b"value = 1\n"
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("main.py", before)])
    workspace_root = store.resolve(workspace.workspace_id)
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=SequenceModel(
            [
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
                        "reason": "按用户目标修改值",
                    },
                    ensure_ascii=False,
                )
            ]
        ),
    )
    task = application.create_task("把 value 修改成 2", workspace_root)
    application.run_until_pause(task.task_id)
    permission = application.get_task(task.task_id).actions[-1].permission_request
    assert permission is not None
    return (
        TestClient(create_agent_stream_app(application, store)),
        application,
        workspace_root / "main.py",
        task.task_id,
        permission.permission_request_id,
    )


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_post_permission_records_user_decision_and_returns_current_state(
    tmp_path: Path,
    decision: str,
) -> None:
    client, application, source_file, task_id, permission_id = prepare_edit_wait(tmp_path)

    response = client.post(
        f"/tasks/{task_id}/permissions/{permission_id}",
        json={"decision": decision, "raw_response": f"用户选择 {decision}"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["task_id"] == task_id
    assert result["status"] == "running"
    action_state = result["actions"][-1]
    assert action_state["permission_decision"]["decision"] == decision
    if decision == "approve":
        assert source_file.read_text(encoding="utf-8") == "value = 2\n"
        assert action_state["observation"]["status"] == "success"
    else:
        assert source_file.read_text(encoding="utf-8") == "value = 1\n"
        assert action_state["observation"]["status"] == "rejected"
    assert application.get_task(task_id).current_status.status.value == "running"


def test_post_permission_rejects_stale_or_unknown_request(tmp_path: Path) -> None:
    client, _, _, task_id, _ = prepare_edit_wait(tmp_path)

    response = client.post(
        f"/tasks/{task_id}/permissions/permission_request_missing",
        json={"decision": "approve", "raw_response": "批准"},
    )

    assert response.status_code in {404, 409}


def test_approved_edit_of_missing_file_records_failure_and_resumes_agent(
    tmp_path: Path,
) -> None:
    """批准时目标已不存在，也必须返回权威失败事实，不能泄漏为 HTTP 500。"""

    client, application, source_file, task_id, permission_id = prepare_edit_wait(
        tmp_path
    )
    source_file.unlink()

    response = client.post(
        f"/tasks/{task_id}/permissions/{permission_id}",
        json={"decision": "approve", "raw_response": "批准并执行"},
    )

    assert response.status_code == 200
    result = response.json()
    action_state = result["actions"][-1]
    assert result["status"] == "running"
    assert action_state["permission_decision"]["decision"] == "approve"
    assert action_state["observation"]["status"] == "failed"
    assert action_state["observation"]["error"]["code"] == "FILE_NOT_FOUND"
    assert application.get_task(task_id).current_status.status.value == "running"
