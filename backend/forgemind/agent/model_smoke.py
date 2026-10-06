"""安全验证真实模型调用和 Decision 解析，不执行任何 Action。"""

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from forgemind.agent.decision_parser import (
    parse_agent_decision_with_feedback,
)
from forgemind.agent.openai_compatible_model import (
    MissingModelApiKeyError,
    OpenAICompatibleClient,
    create_openai_compatible_agent_model,
)
from forgemind.config.model import load_model_provider_config
from forgemind.context.messages import build_agent_turn_input
from forgemind.schema.context import AgentTaskContext
from forgemind.schema.decisions import (
    AgentDecision,
    AgentDecisionParseFailure,
)
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord


@dataclass(frozen=True, slots=True)
class ModelSmokeResult:
    """同时保留模型原始证据和严格解析结果。"""

    raw_response: str
    decision_result: AgentDecision | AgentDecisionParseFailure


def run_model_smoke(
    *,
    config_path: Path,
    project_root: Path,
    environment: Mapping[str, str] | None = None,
    client_factory: Callable[..., OpenAICompatibleClient] | None = None,
) -> ModelSmokeResult:
    """调用一次模型并解析输出；不登记或执行模型产生的 Decision。"""

    # 第一步：调用 load_model_provider_config(config_path)，读取并严格校验
    # TOML 配置；再把配置、environment 和 client_factory 交给模型工厂。
    config = load_model_provider_config(config_path)
    model = create_openai_compatible_agent_model(
        config,
        environment=environment,
        client_factory=client_factory,
    )

    # 第二步：建立最小 AgentTaskContext。任务状态必须是 RUNNING；本次没有
    # Action 历史，所以 recent_actions 为空，同时明确历史完整且没有裁剪。
    context = AgentTaskContext(
        task=TaskRecord(
            task_id="model-smoke-task",
            original_request=(
                "这是模型接入冒烟测试。"
                "请根据当前上下文产生下一步决策，"
                "不要假设存在任何未提供的项目事实。"
            ),
            project_root=str(project_root.resolve()),
        ),
        current_status=TaskStatusRecord(
            task_status_id="model-smoke-status-1",
            task_id="model-smoke-task",
            revision=1,
            status=TaskStatus.RUNNING,
            reason="开始模型接入冒烟测试",
        ),
        recent_actions=(),
        total_action_count=0,
        omitted_action_count=0,
        is_action_history_complete=True,
    )

    # 第三步：调用 build_agent_turn_input(context)，生成与正式 Agent 相同的
    # system + user 消息，然后调用 model.generate(...) 得到原始响应。
    turn_input = build_agent_turn_input(context)
    raw_response = model.generate(turn_input)

    # 第四步：调用 parse_agent_decision_with_feedback(raw_response)，把合法
    # JSON 解析成 Decision，或者把问题保存在 ParseFailure 中。
    decision_result = parse_agent_decision_with_feedback(
        raw_response
    )

    # 第五步：返回 ModelSmokeResult。这里不能调用 Dispatcher、Runtime、
    # Registry 或 Tool，因为冒烟测试只验证模型边界。
    return ModelSmokeResult(
        raw_response=raw_response,
        decision_result=decision_result,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "model.toml"


def main() -> int:
    """运行一次可观察的真实模型冒烟测试。"""

    # Windows 的终端和启动器可能使用不同编码。固定为 UTF-8，使真实调用
    # 阶段和错误信息在 IDE、PowerShell 与自动化日志中保持可读。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"[1/4] 读取模型配置：{DEFAULT_CONFIG_PATH}")
    print("[2/4] 创建模型客户端并发送 ForgeMind 标准消息")

    try:
        result = run_model_smoke(
            config_path=DEFAULT_CONFIG_PATH,
            project_root=PROJECT_ROOT,
        )
    except MissingModelApiKeyError as error:
        print(f"[失败] {error}")
        print(
            "请配置上述环境变量，并重新启动运行此程序的终端或 IDE。"
        )
        return 1
    except Exception as error:
        print(f"[失败] {type(error).__name__}: {error}")
        return 1

    print("[3/4] 模型原始响应：")
    print(result.raw_response)
    print("[4/4] ForgeMind 严格解析结果：")
    print(
        json.dumps(
            result.decision_result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )
    print("[安全边界] 本次没有登记或执行任何 Action。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
