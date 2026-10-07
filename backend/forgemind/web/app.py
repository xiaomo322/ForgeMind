"""ForgeMind 可部署 Web 服务器的生产装配入口。"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn

from forgemind.agent.openai_compatible_model import (
    OpenAICompatibleClient,
    create_openai_compatible_agent_model,
)
from forgemind.application import ForgeMindApplication
from forgemind.config.model import load_model_provider_config
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.web.agent_api import create_agent_stream_app
from forgemind.web.workspaces import FileSystemWorkspaceStore


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class WebSettings:
    """服务器装配需要的非敏感路径和开发跨域配置。"""

    data_dir: Path
    model_config_path: Path
    static_dir: Path
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> WebSettings:
        """从环境变量读取部署配置；API Key 仍由模型适配器单独读取。"""

        values = os.environ if environment is None else environment
        raw_origins = values.get("FORGEMIND_CORS_ORIGINS", "")
        origins = tuple(
            origin.strip() for origin in raw_origins.split(",") if origin.strip()
        )
        return cls(
            data_dir=Path(values.get("FORGEMIND_DATA_DIR", ".forgemind-web")),
            model_config_path=Path(
                values.get(
                    "FORGEMIND_MODEL_CONFIG",
                    str(PROJECT_ROOT / "config" / "model.toml"),
                )
            ),
            static_dir=Path(
                values.get(
                    "FORGEMIND_STATIC_DIR",
                    str(PROJECT_ROOT / "frontend" / "dist"),
                )
            ),
            cors_origins=origins,
        )


def create_web_app(
    settings: WebSettings,
    *,
    environment: Mapping[str, str] | None = None,
    client_factory: Callable[..., OpenAICompatibleClient] | None = None,
) -> FastAPI:
    """连接模型、SQLite、上传目录、REST、SSE 和前端静态资源。"""

    data_dir = settings.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    model_config = load_model_provider_config(settings.model_config_path.resolve())
    model = create_openai_compatible_agent_model(
        model_config,
        environment=environment,
        client_factory=client_factory,
    )
    application = ForgeMindApplication(
        state=SQLiteForgeMindState.open(data_dir / "state.db"),
        model=model,
    )
    workspace_store = FileSystemWorkspaceStore(data_dir / "workspaces")
    app = create_agent_stream_app(application, workspace_store)
    app.title = "ForgeMind"
    app.version = "0.1.0"

    # 暴露给测试和部署诊断读取，不作为浏览器公开 API。
    app.state.forgemind_application = application
    app.state.workspace_store = workspace_store

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Last-Event-ID"],
        )

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    static_dir = settings.static_dir.resolve()

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def frontend(frontend_path: str) -> FileResponse:
        """返回构建资源；非文件路径回退到 SPA 的 index.html。"""

        index_path = static_dir / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="frontend is not built")

        requested = (static_dir / frontend_path).resolve()
        if requested.is_relative_to(static_dir) and requested.is_file():
            return FileResponse(requested)
        return FileResponse(index_path)

    return app


def create_app_from_environment() -> FastAPI:
    """供 Uvicorn `--factory` 使用，避免 import 时过早读取密钥。"""

    return create_web_app(WebSettings.from_environment())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgemind-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """启动开发或单机部署服务器。"""

    args = build_parser().parse_args(argv)
    uvicorn.run(
        "forgemind.web.app:create_app_from_environment",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
