"""验证真实模型冒烟入口只调用和解析，不执行 Action。"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from forgemind.agent.model_smoke import run_model_smoke
from forgemind.schema.decisions import AskUserDecision


def test_model_smoke_loads_config_calls_model_and_parses_decision(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "model.toml"
    config_path.write_text(
        """
[model]
adapter = "openai_compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
timeout_seconds = 60
""".strip(),
        encoding="utf-8",
    )
    raw_response = json.dumps(
        {
            "action_type": "ask_user",
            "reason": "冒烟任务没有提供实际修改目标",
            "question": "你希望检查哪个文件？",
        },
        ensure_ascii=False,
    )
    calls: list[dict[str, Any]] = []

    class FakeCompletions:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=raw_response)
                    )
                ]
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    result = run_model_smoke(
        config_path=config_path,
        project_root=tmp_path,
        environment={"DEEPSEEK_API_KEY": "secret-for-test"},
        client_factory=lambda **kwargs: fake_client,
    )

    assert result.raw_response == raw_response
    assert isinstance(result.decision_result, AskUserDecision)
    assert result.decision_result.question == "你希望检查哪个文件？"
    assert calls[0]["model"] == "deepseek-v4-flash"
    system_message, user_message = calls[0]["messages"]
    assert "不要生成 action_id" in system_message["content"]
    assert '"status": "running"' in user_message["content"]
    assert '"recent_actions": []' in user_message["content"]
