"""观察前端通过 FastAPI 创建 ForgeMind 任务的完整过程。"""

from io import BytesIO
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from fastapi.testclient import TestClient

from forgemind.application import ForgeMindApplication
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.tasks import TaskStatus
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.workspaces import FileSystemWorkspaceStore, WorkspaceUpload


class ModelThatMustNotRun:
    """创建任务只写 State；如果误调用模型，测试应立即失败。"""

    def generate(self, turn_input: AgentTurnInput) -> str:
        raise AssertionError("POST /tasks 不应该调用模型")


def test_post_tasks_creates_persisted_running_task(tmp_path: Path) -> None:
    """创建接口应返回 201，并留下可从 SQLite 读取的 RUNNING 任务。"""

    # 第一步（准备）：建立真实 SQLite State、Application 和 FastAPI 客户端。
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=ModelThatMustNotRun(),
    )
    workspace_store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = workspace_store.create(
        [WorkspaceUpload("calculator.py", b"def price():\n    return 10\n")]
    )
    client = TestClient(create_agent_stream_app(application, workspace_store))

    # 第二步（执行）：模拟前端把用户原话和项目目录作为 JSON 发给后端。
    response = client.post(
        "/tasks",
        json={
            "original_request": "检查项目中的价格计算问题",
            "workspace_id": workspace.workspace_id,
        },
    )
    print("创建任务 HTTP 状态：", response.status_code)
    print("创建任务返回内容：", response.json())

    # 第三步（观察）：使用服务器返回的 task_id 重新读取权威 SQLite State。
    assert response.status_code == 201
    response_data = response.json()
    task_view = application.get_task(response_data["task_id"])
    print("SQLite 中的用户原话：", task_view.task.original_request)
    print("SQLite 中的项目目录：", task_view.task.project_root)
    print("SQLite 中的任务状态：", task_view.current_status.status.value)
    print("SQLite 中的状态版本：", task_view.current_status.revision)

    # 第四步（断言）：HTTP 返回值和 SQLite 权威事实必须完全对应。
    assert response_data == {
        "task_id": task_view.task.task_id,
        "original_request": "检查项目中的价格计算问题",
        "workspace_id": workspace.workspace_id,
        "status": "running",
        "revision": 1,
    }
    assert task_view.current_status.status is TaskStatus.RUNNING
    assert task_view.current_status.revision == 1
    assert task_view.actions == ()
    assert task_view.task.project_root == str(workspace_store.resolve(workspace.workspace_id))


def test_post_tasks_rejects_blank_user_request(tmp_path: Path) -> None:
    """只有空白符的用户请求不能进入 Application 或 SQLite。"""

    database_path = tmp_path / "state.db"
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database_path),
        model=ModelThatMustNotRun(),
    )
    workspace_store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = workspace_store.create([WorkspaceUpload("main.py", b"pass\n")])
    # 关闭测试客户端的服务器异常转抛，才能观察 API 实际返回的状态码。
    client = TestClient(
        create_agent_stream_app(application, workspace_store),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/tasks",
        json={
            "original_request": "   ",
            "workspace_id": workspace.workspace_id,
        },
    )
    with sqlite3.connect(database_path) as connection:
        stored_task_count = connection.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0]
    print("空白任务请求的 HTTP 状态：", response.status_code)
    print("空白任务请求后的任务数量：", stored_task_count)

    assert response.status_code == 422
    assert stored_task_count == 0


def test_post_tasks_rejects_unknown_workspace_without_creating_task(
    tmp_path: Path,
) -> None:
    """未知 workspace_id 不能创建一个随后必然无法执行的任务。"""

    database_path = tmp_path / "state.db"
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database_path),
        model=ModelThatMustNotRun(),
    )
    workspace_store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    client = TestClient(create_agent_stream_app(application, workspace_store))

    response = client.post(
        "/tasks",
        json={
            "original_request": "检查项目",
            "workspace_id": "workspace_00000000-0000-0000-0000-000000000000",
        },
    )
    with sqlite3.connect(database_path) as connection:
        stored_task_count = connection.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0]
    print("不存在目录的 HTTP 状态：", response.status_code)
    print("不存在目录请求后的任务数量：", stored_task_count)

    assert response.status_code == 404
    assert stored_task_count == 0
    assert "project_root" not in response.text


def test_get_tasks_lists_persisted_tasks_newest_first_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    first_application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database_path),
        model=ModelThatMustNotRun(),
    )
    first_store = FileSystemWorkspaceStore(workspace_root)
    first_workspace = first_store.create([WorkspaceUpload("first.py", b"pass\n")])
    second_workspace = first_store.create([WorkspaceUpload("second.py", b"pass\n")])
    first_client = TestClient(create_agent_stream_app(first_application, first_store))
    first = first_client.post(
        "/tasks",
        json={"original_request": "第一个任务", "workspace_id": first_workspace.workspace_id},
    ).json()
    second = first_client.post(
        "/tasks",
        json={"original_request": "第二个任务", "workspace_id": second_workspace.workspace_id},
    ).json()

    restarted_application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database_path),
        model=ModelThatMustNotRun(),
    )
    restarted_store = FileSystemWorkspaceStore(workspace_root)
    response = TestClient(
        create_agent_stream_app(restarted_application, restarted_store)
    ).get("/tasks?limit=10")

    assert response.status_code == 200
    assert response.json() == {
        "tasks": [
            {
                "task_id": second["task_id"],
                "original_request": "第二个任务",
                "workspace_id": second_workspace.workspace_id,
                "status": "running",
                "revision": 1,
            },
            {
                "task_id": first["task_id"],
                "original_request": "第一个任务",
                "workspace_id": first_workspace.workspace_id,
                "status": "running",
                "revision": 1,
            },
        ]
    }


def test_get_task_workspace_zip_downloads_current_project(tmp_path: Path) -> None:
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=ModelThatMustNotRun(),
    )
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    workspace = store.create_from_zip(
        _project_zip({"src/main.py": b"value = 1\n", "README.md": b"# Demo\n"})
    )
    client = TestClient(create_agent_stream_app(application, store))
    task = client.post(
        "/tasks",
        json={"original_request": "检查项目", "workspace_id": workspace.workspace_id},
    ).json()

    files_response = client.get(f"/tasks/{task['task_id']}/files")
    assert [item["path"] for item in files_response.json()["files"]] == [
        "README.md",
        "src/main.py",
    ]

    response = client.get(f"/tasks/{task['task_id']}/workspace.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["README.md", "src/main.py"]
        assert archive.read("src/main.py") == b"value = 1\n"


def _project_zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()
