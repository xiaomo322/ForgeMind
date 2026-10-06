"""从 Python 代码调用 ForgeMind，修复当前示例项目。"""

from __future__ import annotations

import json
from pathlib import Path

from forgemind.agent.openai_compatible_model import (
    create_openai_compatible_agent_model,
)
from forgemind.application import ForgeMindApplication
from forgemind.config.model import load_model_provider_config
from forgemind.schema.tasks import TaskStatus
from forgemind.state.sqlite_state import SQLiteForgeMindState


# run_agent.py 位于 examples/calculator_demo，向上两级是 ForgeMind 仓库根目录。
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_CONFIG_PATH = REPOSITORY_ROOT / "config" / "model.toml"
DATABASE_PATH = PROJECT_ROOT / ".forgemind" / "code-entry-state.db"


def create_application() -> ForgeMindApplication:
    """从配置文件、环境变量和 SQLite 数据库组装应用服务。"""

    # 配置文件只保存厂商 URL、模型名称和 API Key 环境变量的名字。
    # create_openai_compatible_agent_model() 会从环境变量读取真实 Key。
    model_config = load_model_provider_config(MODEL_CONFIG_PATH)
    model = create_openai_compatible_agent_model(model_config)

    # SQLiteForgeMindState 是任务、Action、权限和 Observation 的权威来源。
    state = SQLiteForgeMindState.open(DATABASE_PATH)
    return ForgeMindApplication(state=state, model=model)


def print_task_state(app: ForgeMindApplication, task_id: str) -> None:
    """打印当前完整任务视图，便于观察 Agent 的真实执行记录。"""

    view = app.get_task(task_id)
    print(
        json.dumps(
            view.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )


def resolve_waiting_user(
    app: ForgeMindApplication,
    task_id: str,
) -> None:
    """处理当前最新 Action 对应的问题或权限请求。"""

    view = app.get_task(task_id)
    latest = view.actions[-1]

    if latest.action.action_type == "ask_user":
        print(f"\nAgent 问题：{latest.action.question}")
        if latest.action.options:
            print("可选项：", " / ".join(latest.action.options))
        answer = input("你的回答：").strip()
        app.answer_question(
            task_id=task_id,
            question_action_id=latest.action.action_id,
            raw_response=answer,
            selected_option=(
                answer
                if latest.action.options and answer in latest.action.options
                else None
            ),
        )
        return

    request = latest.permission_request
    if request is None:
        raise RuntimeError("任务处于 WAITING_USER，但最新 Action 没有待处理交互")

    print("\nAgent 请求执行：")
    print(
        json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )
    approved = input("是否批准这一次 Action？[y/N]：").strip().lower() == "y"
    app.decide_permission(
        task_id=task_id,
        permission_request_id=request.permission_request_id,
        approve=approved,
        raw_response="用户在 Python 示例入口中批准" if approved else "用户拒绝",
    )


def main() -> None:
    """创建一个任务，并驱动它直到完成或需要人工处理异常。"""

    app = create_application()
    task = app.create_task(
        "修复 calculator.py 中 add 函数的错误，并运行 tests/test_calculator.py 验证",
        PROJECT_ROOT,
    )
    print(f"已创建任务：{task.task_id}")

    while True:
        result = app.run_until_pause(task.task_id, max_steps=10)
        print(f"\n当前状态：{result.status.value}")

        if result.parse_failure is not None:
            print("模型输出没有通过严格 Schema 校验：")
            print(result.parse_failure.model_dump_json(indent=2))
            break

        if result.status is TaskStatus.WAITING_USER:
            resolve_waiting_user(app, task.task_id)
            continue

        if result.status is TaskStatus.COMPLETED:
            print("\n任务已经完成，最终 State：")
            print_task_state(app, task.task_id)
            break

        if result.status in {TaskStatus.BLOCKED, TaskStatus.CANCELLED}:
            print_task_state(app, task.task_id)
            break

        # 达到 max_steps 时任务仍可能是 RUNNING。继续循环即可，但输出提醒，
        # 避免把“本批次数量用完”误解为任务已经完成。
        print("本批次达到最大 Agent 步数，继续下一批次。")


if __name__ == "__main__":
    main()
