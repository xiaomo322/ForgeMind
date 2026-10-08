"""任务开始后追加消息和 Python 附件的 API 闭环。"""

from pathlib import Path

from fastapi.testclient import TestClient

from forgemind.application import ForgeMindApplication
from forgemind.context.builder import build_agent_task_context
from forgemind.schema.context import AgentTurnInput
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.workspaces import FileSystemWorkspaceStore, WorkspaceUpload


class ModelThatMustNotRun:
    def generate(self, turn_input: AgentTurnInput) -> str:
        raise AssertionError("消息 API 不应该直接调用模型")


def test_stage_and_send_follow_up_then_apply_at_boundary(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    application = ForgeMindApplication(state=state, model=ModelThatMustNotRun())
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create([WorkspaceUpload("app.py", b"value = 1\n")])
    client = TestClient(create_agent_stream_app(application, store))
    created = client.post(
        "/tasks",
        json={"original_request": "检查项目", "workspace_id": workspace.workspace_id},
    ).json()
    task_id = created["task_id"]

    upload = client.post(
        f"/tasks/{task_id}/files",
        files={"files": ("extra.py", b"extra = 2\n", "text/x-python")},
    )
    assert upload.status_code == 201
    upload_id = upload.json()["uploads"][0]["upload_id"]
    project_root = store.resolve(workspace.workspace_id)
    assert not (project_root / "extra.py").exists()

    sent = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "同时检查新文件", "attachment_upload_ids": [upload_id]},
    )
    assert sent.status_code == 202
    assert sent.json()["delivery"] == "queued"
    assert client.get(f"/tasks/{task_id}").json()["messages"][0]["delivery"] == "queued"

    application.apply_queued_messages(task_id)

    restored = client.get(f"/tasks/{task_id}").json()
    assert restored["messages"][0]["delivery"] == "applied"
    assert restored["messages"][0]["attachments"][0]["path"] == "extra.py"
    assert (project_root / "extra.py").read_bytes() == b"extra = 2\n"
    assert str(store.storage_root) not in str(restored)
    context = build_agent_task_context(application.get_task(task_id), max_action_count=20)
    assert context.recent_messages[0].message.content == "同时检查新文件"
    assert context.recent_messages[0].attachments[0].path == "extra.py"

    orphan = client.post(
        f"/tasks/{task_id}/files",
        files={"files": ("unused.py", b"unused = True\n", "text/x-python")},
    ).json()["uploads"][0]
    deleted = client.delete(f"/tasks/{task_id}/files/staged/{orphan['upload_id']}")
    assert deleted.status_code == 204
    assert all(
        item["path"] != "unused.py"
        for item in client.get(f"/tasks/{task_id}/files").json()["files"]
    )

