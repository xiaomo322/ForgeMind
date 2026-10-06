"""验证单一 TOML 模型配置的严格读取边界。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.config.model import load_model_provider_config


def _write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "model.toml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_model_provider_config_returns_validated_model(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        """
[model]
adapter = "openai_compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
""".strip(),
    )

    config = load_model_provider_config(config_path)

    assert config.adapter == "openai_compatible"
    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-v4-flash"
    assert config.api_key_env == "DEEPSEEK_API_KEY"
    assert config.timeout_seconds == 60


@pytest.mark.parametrize(
    "content",
    [
        'adapter = "openai_compatible"',
        """
[model]
adapter = "openai_compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
unexpected = "不能静默忽略"
""".strip(),
        """
[model]
adapter = "openai_compatible"
base_url = ""
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
""".strip(),
        """
[model]
adapter = "openai_compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 0
""".strip(),
    ],
)
def test_invalid_model_provider_config_is_rejected(
    tmp_path: Path,
    content: str,
) -> None:
    config_path = _write_config(tmp_path, content)

    with pytest.raises(ValidationError):
        load_model_provider_config(config_path)
