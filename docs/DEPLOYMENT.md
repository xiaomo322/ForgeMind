# Deployment Guide

## Container layout

The Dockerfile uses two stages:

1. Node.js builds the React application into static assets.
2. Python installs the locked ForgeMind package and serves the API, SSE endpoints and frontend from one FastAPI process.

Runtime data is stored under `/data`:

```text
/data/state.db       task, action, permission, message and observation records
/data/workspaces/    active and staged task workspaces
```

Compose mounts this directory from the `forgemind-data` named volume.

## Start

```bash
cp .env.example .env
```

Set the server-side model key in `.env`:

```dotenv
DEEPSEEK_API_KEY=your_api_key
```

Build and start:

```bash
docker compose up --build -d
curl http://127.0.0.1:8000/health
docker compose logs -f forgemind
```

Compose intentionally binds to `127.0.0.1:8000`. For remote use, place an authenticated HTTPS reverse proxy in front of the service.

## Reverse proxy requirements

SSE must not be buffered. An Nginx location needs at least:

```nginx
client_max_body_size 11m;

location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```

Add authentication at the proxy or gateway. Do not expose the Compose port directly to the internet.

## Model provider configuration

`config/model.toml` contains non-secret OpenAI-compatible settings:

```toml
base_url = "https://api.deepseek.com"
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
```

To use another compatible provider, change this file or point `FORGEMIND_MODEL_CONFIG` to another TOML file. Keep the actual key in the environment variable named by `api_key_env`.

Optional server settings:

| Variable | Default | Purpose |
|---|---|---|
| `FORGEMIND_DATA_DIR` | `.forgemind-web` | SQLite and workspace storage |
| `FORGEMIND_MODEL_CONFIG` | `config/model.toml` | Provider configuration path |
| `FORGEMIND_STATIC_DIR` | `frontend/dist` | Built frontend assets |
| `FORGEMIND_CORS_ORIGINS` | empty | Comma-separated development origins |

## Operations

Rebuild after an update:

```bash
docker compose up --build -d
```

Stop while preserving data:

```bash
docker compose down
```

Back up the persistent volume:

```bash
docker run --rm \
  -v forgemind-data:/data:ro \
  -v "$PWD:/backup" \
  alpine tar -czf /backup/forgemind-data.tgz -C /data .
```

Stop writes before a backup when a consistent SQLite/workspace snapshot is required. `docker compose down -v` permanently deletes the named volume and should only be used for an intentional full reset.
