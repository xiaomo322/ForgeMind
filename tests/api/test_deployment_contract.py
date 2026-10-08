from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_container_runs_the_application_factory_as_a_non_root_user() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "frontend-build" in dockerfile
    assert "forgemind.web.app:create_app_from_environment" in dockerfile
    assert "--factory" in dockerfile
    assert "USER forgemind" in dockerfile
    assert "uv:0.11.6" in dockerfile
    assert "uv sync --locked --no-dev" in dockerfile
    assert "pip install" not in dockerfile


def test_compose_persists_runtime_state_and_passes_api_key() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY" in compose
    assert "forgemind-data:/data" in compose
    assert "127.0.0.1:8000:8000" in compose


def test_compose_reduces_container_privileges() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose
    assert "- ALL" in compose
    assert "/tmp:size=256m,mode=1777" in compose


def test_example_environment_file_never_contains_a_real_secret() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY=" in example
    assert "sk-" not in example
