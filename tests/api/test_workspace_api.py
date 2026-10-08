"""浏览器 multipart 上传工作区的 API 测试。"""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from forgemind.application import ForgeMindApplication
from forgemind.schema.context import AgentTurnInput
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.request_limits import MAX_WORKSPACE_UPLOAD_REQUEST_BYTES
from forgemind.web.workspaces import FileSystemWorkspaceStore


class ModelThatMustNotRun:
    def generate(self, turn_input: AgentTurnInput) -> str:
        raise AssertionError("上传工作区不应该调用模型")


def make_client(tmp_path: Path) -> tuple[TestClient, FileSystemWorkspaceStore]:
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(tmp_path / "state.db"),
        model=ModelThatMustNotRun(),
    )
    store = FileSystemWorkspaceStore(tmp_path / "workspaces")
    return TestClient(create_agent_stream_app(application, store)), store


def test_post_workspace_archive_creates_nested_persistent_workspace(
    tmp_path: Path,
) -> None:
    client, store = make_client(tmp_path)
    content = BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr("src/main.py", b"print('ok')\n")
        archive.writestr("README.md", "# Demo\n".encode())

    response = client.post(
        "/workspaces/archive",
        files={"archive": ("demo.zip", content.getvalue(), "application/zip")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert [item["path"] for item in payload["files"]] == [
        "README.md",
        "src/main.py",
    ]
    assert (store.resolve(payload["workspace_id"]) / "src" / "main.py").is_file()


def test_post_workspaces_persists_python_files(tmp_path: Path) -> None:
    client, store = make_client(tmp_path)

    response = client.post(
        "/workspaces",
        files=[
            (
                "files",
                ("calculator.py", b"def add(a, b):\n    return a + b\n", "text/x-python"),
            ),
            (
                "files",
                ("test_calculator.py", b"def test_add():\n    assert 1 + 1 == 2\n", "text/x-python"),
            ),
        ],
    )

    assert response.status_code == 201
    result = response.json()
    assert result["file_count"] == 2
    assert [file["path"] for file in result["files"]] == [
        "calculator.py",
        "test_calculator.py",
    ]
    assert (store.resolve(result["workspace_id"]) / "calculator.py").is_file()
    assert "workspaces" not in response.text


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("notes.txt", b"text", 415),
        ("../secret.py", b"pass\n", 422),
        ("broken.py", b"\xff", 422),
        ("large.py", b"x" * (1024 * 1024 + 1), 413),
    ],
    ids=["unsupported-type", "unsafe-name", "invalid-utf8", "too-large"],
)
def test_post_workspaces_maps_upload_errors(
    tmp_path: Path,
    filename: str,
    content: bytes,
    expected_status: int,
) -> None:
    client, _ = make_client(tmp_path)

    response = client.post(
        "/workspaces",
        files=[("files", (filename, content, "application/octet-stream"))],
    )

    assert response.status_code == expected_status
    assert str(tmp_path.resolve()) not in response.text


def test_post_workspaces_rejects_duplicate_names_with_conflict(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)

    response = client.post(
        "/workspaces",
        files=[
            ("files", ("main.py", b"pass\n", "text/x-python")),
            ("files", ("MAIN.py", b"pass\n", "text/x-python")),
        ],
    )

    assert response.status_code == 409


def test_post_workspaces_rejects_request_body_before_multipart_parsing(
    tmp_path: Path,
) -> None:
    client, _ = make_client(tmp_path)

    response = client.post(
        "/workspaces",
        content=b"x" * (MAX_WORKSPACE_UPLOAD_REQUEST_BYTES + 1),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "workspace upload request is too large"}


def test_post_workspaces_rejects_too_many_parts_before_reading_files(
    tmp_path: Path,
) -> None:
    client, _ = make_client(tmp_path)

    response = client.post(
        "/workspaces",
        files=[
            ("files", (f"file_{index}.py", b"pass\n", "text/x-python"))
            for index in range(21)
        ],
    )

    assert response.status_code == 413
