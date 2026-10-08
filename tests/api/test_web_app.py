"""生产 Web 应用装配与静态站点托管测试。"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from forgemind.web.app import WebSettings, create_web_app


class FakeCompletions:
    def create(self, **kwargs: Any) -> Any:
        raise AssertionError("构造 Web 应用不应调用模型")


class FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


def write_model_config(path: Path) -> None:
    path.write_text(
        """
[model]
adapter = "openai_compatible"
base_url = "https://model.example/v1"
model = "test-model"
api_key_env = "TEST_MODEL_KEY"
timeout_seconds = 30
""".strip(),
        encoding="utf-8",
    )


def test_create_web_app_wires_persistent_data_and_health(tmp_path: Path) -> None:
    config_path = tmp_path / "model.toml"
    write_model_config(config_path)
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>ForgeMind</h1>", encoding="utf-8")
    data_dir = tmp_path / "data"

    app = create_web_app(
        WebSettings(
            data_dir=data_dir,
            model_config_path=config_path,
            static_dir=static_dir,
            cors_origins=("http://localhost:5173",),
        ),
        environment={"TEST_MODEL_KEY": "test-secret"},
        client_factory=FakeClient,
    )
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    assert app.state.forgemind_application.state.database_path == (
        data_dir / "state.db"
    ).resolve()
    assert app.state.workspace_store.storage_root == (data_dir / "workspaces").resolve()
    assert (data_dir / "workspaces").is_dir()


def test_static_files_and_frontend_routes_return_built_app(tmp_path: Path) -> None:
    config_path = tmp_path / "model.toml"
    write_model_config(config_path)
    static_dir = tmp_path / "dist"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>ForgeMind UI</h1>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")
    app = create_web_app(
        WebSettings(
            data_dir=tmp_path / "data",
            model_config_path=config_path,
            static_dir=static_dir,
            cors_origins=(),
        ),
        environment={"TEST_MODEL_KEY": "test-secret"},
        client_factory=FakeClient,
    )
    client = TestClient(app)

    assert client.get("/").text == "<h1>ForgeMind UI</h1>"
    assert client.get("/assets/app.js").text == "console.log('ok')"
    assert client.get("/tasks/current-ui-view").status_code == 404
    assert client.get("/workspace/new").text == "<h1>ForgeMind UI</h1>"


def test_web_responses_include_browser_security_headers(tmp_path: Path) -> None:
    """部署入口应给 API 和静态页面统一增加基础浏览器安全边界。"""

    config_path = tmp_path / "model.toml"
    write_model_config(config_path)
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>ForgeMind</h1>", encoding="utf-8")
    app = create_web_app(
        WebSettings(
            data_dir=tmp_path / "data",
            model_config_path=config_path,
            static_dir=static_dir,
        ),
        environment={"TEST_MODEL_KEY": "test-secret"},
        client_factory=FakeClient,
    )
    client = TestClient(app)

    for path in ("/health", "/"):
        response = client.get(path)
        print(path, "安全响应头：", dict(response.headers))
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "default-src 'self'" in response.headers["content-security-policy"]


def test_web_settings_read_environment_without_guessing_paths(tmp_path: Path) -> None:
    settings = WebSettings.from_environment(
        {
            "FORGEMIND_DATA_DIR": str(tmp_path / "data"),
            "FORGEMIND_MODEL_CONFIG": str(tmp_path / "model.toml"),
            "FORGEMIND_STATIC_DIR": str(tmp_path / "dist"),
            "FORGEMIND_CORS_ORIGINS": "http://localhost:5173, http://127.0.0.1:5173",
        }
    )

    assert settings.data_dir == tmp_path / "data"
    assert settings.model_config_path == tmp_path / "model.toml"
    assert settings.static_dir == tmp_path / "dist"
    assert settings.cors_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
