FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

# 先复制依赖清单，只有依赖变化时才重新安装，能够复用 Docker 缓存。
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts

COPY frontend/ ./
RUN pnpm build


FROM python:3.11-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORGEMIND_DATA_DIR=/data \
    FORGEMIND_MODEL_CONFIG=/app/config/model.toml \
    FORGEMIND_STATIC_DIR=/app/frontend/dist \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/ ./backend/
COPY config/ ./config/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 10001 forgemind \
    && mkdir -p /data \
    && chown -R forgemind:forgemind /data

# Agent 会执行项目代码，因此容器进程不能拥有 root 权限。
USER forgemind

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "forgemind.web.app:create_app_from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000"]
