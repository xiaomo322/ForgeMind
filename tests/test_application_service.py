import json
from dataclasses import dataclass, field
from pathlib import Path

from forgemind.application import ForgeMindApplication
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.tasks import TaskStatus
from forgemind.state.sqlite_state import SQLiteForgeMindState


@dataclass
class SequenceModel:
    responses: list[str]
    inputs: list[AgentTurnInput] = field(default_factory=list)

    def generate(self, turn_input: AgentTurnInput) -> str:
        self.inputs.append(turn_input)
        return self.responses.pop(0)


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False)


def test_application_runs_immediate_tools_until_complete(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    model = SequenceModel(
        [
            _json(
                {
                    "action_type": "tool_call",
                    "tool_name": "search_code",
                    "arguments": {"query": "value", "scope": "."},
                    "reason": "定位代码",
                }
            ),
            _json(
                {
                    "action_type": "complete",
                    "reason": "已经取得所需证据",
                    "summary": "定位完成",
                }
            ),
        ]
    )
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    app = ForgeMindApplication(state=state, model=model)
    task = app.create_task(
        "定位 value",
        tmp_path,
        next_task_id=lambda: "task-001",
        next_task_status_id=lambda: "status-001",
    )

    result = app.run_until_pause(task.task_id, max_steps=5)

    assert result.status is TaskStatus.COMPLETED
    assert result.steps_executed == 2
    assert len(model.inputs) == 2
    assert len(state.get_task_view(task.task_id).actions) == 2


def test_application_stops_on_parse_failure_without_inventing_action(
    tmp_path: Path,
) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    app = ForgeMindApplication(state=state, model=SequenceModel(["not json"]))
    task = app.create_task(
        "分析项目",
        tmp_path,
        next_task_id=lambda: "task-001",
        next_task_status_id=lambda: "status-001",
    )

    result = app.run_until_pause(task.task_id, max_steps=5)

    assert result.status is TaskStatus.RUNNING
    assert result.parse_failure is not None
    assert state.get_task_view(task.task_id).actions == ()
