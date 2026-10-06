import json
from dataclasses import dataclass, field
from pathlib import Path

from forgemind.application import ForgeMindApplication
from forgemind.runtime.run_command_handler import handle_run_command_decision
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.decisions import RunCommandToolCallDecision
from forgemind.schema.permissions import (
    PermissionDecision,
    PermissionDecisionRecord,
)
from forgemind.schema.tasks import TaskStatus, TaskStatusRecord
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

    observed_steps: list[tuple[int, object]] = []
    result = app.run_until_pause(
        task.task_id,
        max_steps=5,
        on_step=lambda number, step: observed_steps.append((number, step)),
    )

    assert result.status is TaskStatus.COMPLETED
    assert result.steps_executed == 2
    assert len(model.inputs) == 2
    assert len(state.get_task_view(task.task_id).actions) == 2
    assert [number for number, _ in observed_steps] == [1, 2]
    assert [
        step.turn_result.raw_response for _, step in observed_steps
    ] == [
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


def test_application_records_unknown_result_instead_of_replaying_command(
    tmp_path: Path,
) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    app = ForgeMindApplication(
        state=state,
        model=SequenceModel(
            [
                _json(
                    {
                        "action_type": "complete",
                        "reason": "中断证据已经记录",
                        "summary": "停止自动重试",
                    }
                )
            ]
        ),
    )
    task = app.create_task(
        "执行命令",
        tmp_path,
        next_task_id=lambda: "task-001",
        next_task_status_id=lambda: "status-001",
    )
    waiting = handle_run_command_decision(
        RunCommandToolCallDecision(
            action_type="tool_call",
            tool_name="run_command",
            arguments={
                "program": "python",
                "args": ("-V",),
                "working_directory": ".",
                "timeout_seconds": 30,
            },
            reason="执行命令",
        ),
        task_id=task.task_id,
        state=state,
        next_action_id=lambda: "action-001",
        next_permission_request_id=lambda: "request-001",
        next_task_status_id=lambda: "status-002",
    )
    state.record_process_permission_approval_executing(
        PermissionDecisionRecord(
            permission_decision_id="decision-001",
            permission_request_id=waiting.permission_request.permission_request_id,
            task_id=task.task_id,
            action_id=waiting.action.action_id,
            decision=PermissionDecision.APPROVE,
            source="user",
            raw_response="同意",
        ),
        TaskStatusRecord(
            task_status_id="status-003",
            task_id=task.task_id,
            revision=3,
            status=TaskStatus.EXECUTING,
            reason="执行命令",
        ),
    )

    result = ForgeMindApplication(
        state=SQLiteForgeMindState.open(state.database_path),
        model=app.model,
    ).run_until_pause(task.task_id)

    assert result.status is TaskStatus.COMPLETED
    recovered = state.get_task_view(task.task_id).actions[0].observation
    assert recovered is not None
    assert recovered.error.code.value == "EXECUTION_RESULT_UNKNOWN"
