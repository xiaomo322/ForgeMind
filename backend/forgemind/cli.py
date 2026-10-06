"""ForgeMind V0.1 命令行入口。"""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from forgemind.agent.openai_compatible_model import (
    create_openai_compatible_agent_model,
)
from forgemind.application import ApplicationRunResult, ForgeMindApplication
from forgemind.config.model import load_model_provider_config
from forgemind.state.sqlite_state import SQLiteForgeMindState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "model.toml"


class _ModelNotRequired:
    def generate(self, turn_input: object) -> str:
        raise RuntimeError("该命令不需要也不能调用模型")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgemind")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(".forgemind/state.db"),
        help="SQLite 状态数据库路径",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="模型 TOML 配置路径",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="创建任务并运行至暂停或完成")
    start.add_argument("request")
    start.add_argument("--project-root", type=Path, default=Path.cwd())
    start.add_argument("--max-steps", type=int, default=20)
    start.add_argument("--no-run", action="store_true")

    run = subparsers.add_parser("run", help="继续运行 RUNNING 任务")
    run.add_argument("task_id")
    run.add_argument("--max-steps", type=int, default=20)

    status = subparsers.add_parser("status", help="查看完整权威任务视图")
    status.add_argument("task_id")

    answer = subparsers.add_parser("answer", help="回答 ask_user Action")
    answer.add_argument("task_id")
    answer.add_argument("question_action_id")
    answer.add_argument("response")
    answer.add_argument("--selected-option")

    for command in ("approve", "reject"):
        permission = subparsers.add_parser(command)
        permission.add_argument("task_id")
        permission.add_argument("permission_request_id")
        permission.add_argument("--response", default=("同意" if command == "approve" else "拒绝"))

    return parser


def _application(args: argparse.Namespace, *, needs_model: bool) -> ForgeMindApplication:
    state = SQLiteForgeMindState.open(args.database)
    if needs_model:
        config = load_model_provider_config(args.config)
        model = create_openai_compatible_agent_model(config)
    else:
        model = _ModelNotRequired()
    return ForgeMindApplication(state=state, model=model)


def _run_json(result: ApplicationRunResult) -> dict[str, object]:
    return {
        "task_id": result.task_id,
        "status": result.status.value,
        "steps_executed": result.steps_executed,
        "parse_failure": (
            None
            if result.parse_failure is None
            else result.parse_failure.model_dump(mode="json")
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        needs_model = args.command in {"start", "run"} and not getattr(
            args, "no_run", False
        )
        app = _application(args, needs_model=needs_model)
        if args.command == "start":
            task = app.create_task(args.request, args.project_root)
            payload: dict[str, object]
            if args.no_run:
                payload = {
                    "task_id": task.task_id,
                    "status": "running",
                    "steps_executed": 0,
                }
            else:
                payload = _run_json(
                    app.run_until_pause(task.task_id, max_steps=args.max_steps)
                )
        elif args.command == "run":
            payload = _run_json(
                app.run_until_pause(args.task_id, max_steps=args.max_steps)
            )
        elif args.command == "status":
            payload = app.get_task(args.task_id).model_dump(mode="json")
        elif args.command == "answer":
            app.answer_question(
                task_id=args.task_id,
                question_action_id=args.question_action_id,
                raw_response=args.response,
                selected_option=args.selected_option,
            )
            payload = app.get_task(args.task_id).model_dump(mode="json")
        else:
            app.decide_permission(
                task_id=args.task_id,
                permission_request_id=args.permission_request_id,
                approve=args.command == "approve",
                raw_response=args.response,
            )
            payload = app.get_task(args.task_id).model_dump(mode="json")
    except Exception as error:
        print(
            json.dumps(
                {"error": type(error).__name__, "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
