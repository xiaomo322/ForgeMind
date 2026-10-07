"""公开任务状态接口的恢复能力测试。"""

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from forgemind.application import ForgeMindApplication
from forgemind.schema.context import AgentTurnInput
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.workspaces import FileSystemWorkspaceStore, WorkspaceUpload


@dataclass
class SequenceModel:
    responses: list[str]

    def generate(self, turn_input: AgentTurnInput) -> str:
        return self.responses.pop(0)


def test_get_task_restores_waiting_question_without_exposing_server_path(
    tmp_path: Path,
) -> None:
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("main.py", b"value = 1\n")])
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=SequenceModel(
            [
                json.dumps(
                    {
                        "action_type": "ask_user",
                        "reason": "目标存在歧义",
                        "question": "需要把 value 修改成多少？",
                        "options": ["2", "3"],
                    },
                    ensure_ascii=False,
                )
            ]
        ),
    )
    task = application.create_task("修改 value", store.resolve(workspace.workspace_id))
    application.run_until_pause(task.task_id)
    client = TestClient(create_agent_stream_app(application, store))

    response = client.get(f"/tasks/{task.task_id}")

    assert response.status_code == 200
    result = response.json()
    assert result["task_id"] == task.task_id
    assert result["original_request"] == "修改 value"
    assert result["status"] == "waiting_user"
    assert result["revision"] == 2
    assert result["actions"][0]["sequence"] == 1
    assert result["actions"][0]["action"]["action_type"] == "ask_user"
    assert result["actions"][0]["action"]["question"] == "需要把 value 修改成多少？"
    assert result["actions"][0]["user_response"] is None
    assert "project_root" not in response.text
    assert str(tmp_path.resolve()) not in response.text


def test_get_unknown_task_returns_404(tmp_path: Path) -> None:
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=SequenceModel([]),
    )
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    client = TestClient(create_agent_stream_app(application, store))

    response = client.get("/tasks/task_missing")

    assert response.status_code == 404
