import json
from dataclasses import dataclass
from pathlib import Path

from forgemind.application import ForgeMindApplication
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.context import AgentTurnInput
from forgemind.schema.permissions import PermissionDecision
from forgemind.schema.tasks import TaskStatus
from forgemind.state.sqlite_state import SQLiteForgeMindState


@dataclass
class SequenceModel:
    responses: list[str]

    def generate(self, turn_input: AgentTurnInput) -> str:
        return self.responses.pop(0)


def _decision(**value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def test_full_edit_verify_complete_flow_survives_restarts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    before = b"def discount():\n    return 1\n"
    after = b"def discount():\n    return 2\n"
    (project / "pricing.py").write_bytes(before)
    (tests_dir / "test_pricing.py").write_text(
        "import pricing\n\ndef test_discount():\n    assert pricing.discount() == 2\n",
        encoding="utf-8",
    )
    model = SequenceModel(
        [
            _decision(
                action_type="tool_call",
                tool_name="search_code",
                arguments={"query": "discount", "scope": "."},
                reason="定位折扣实现",
            ),
            _decision(
                action_type="tool_call",
                tool_name="read_file",
                arguments={"path": "pricing.py"},
                reason="读取完整实现",
            ),
            _decision(
                action_type="tool_call",
                tool_name="edit_file",
                arguments={
                    "path": "pricing.py",
                    "old_text": "return 1",
                    "new_text": "return 2",
                    "expected_version": calculate_content_version(before),
                },
                reason="修复折扣返回值",
            ),
            _decision(
                action_type="tool_call",
                tool_name="run_tests",
                arguments={
                    "targets": ("tests/test_pricing.py",),
                    "timeout_seconds": 30,
                },
                reason="运行真实测试验证修改",
            ),
            _decision(
                action_type="complete",
                reason="修改与真实测试证据均已取得",
                summary="折扣返回值已修复，测试通过",
            ),
        ]
    )
    database = tmp_path / "state.db"
    first = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database), model=model
    )
    task = first.create_task("把 discount 返回值改成 2", project)

    waiting_edit = first.run_until_pause(task.task_id)
    assert waiting_edit.status is TaskStatus.WAITING_USER
    edit_request = first.get_task(task.task_id).actions[-1].permission_request
    assert edit_request is not None and edit_request.tool_name == "edit_file"

    second = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database), model=model
    )
    edit_result = second.decide_permission(
        task_id=task.task_id,
        permission_request_id=edit_request.permission_request_id,
        approve=True,
        raw_response="同意这次精确修改",
    )
    assert edit_result.decision.decision is PermissionDecision.APPROVE
    assert (project / "pricing.py").read_bytes() == after

    waiting_tests = second.run_until_pause(task.task_id)
    assert waiting_tests.status is TaskStatus.WAITING_USER
    test_request = second.get_task(task.task_id).actions[-1].permission_request
    assert test_request is not None and test_request.tool_name == "run_tests"

    third = ForgeMindApplication(
        state=SQLiteForgeMindState.open(database), model=model
    )
    test_result = third.decide_permission(
        task_id=task.task_id,
        permission_request_id=test_request.permission_request_id,
        approve=True,
        raw_response="同意运行这一个测试文件",
    )
    assert test_result.observation.status == "success"
    assert test_result.observation.result.test_outcome.value == "passed"

    completed = third.run_until_pause(task.task_id)
    assert completed.status is TaskStatus.COMPLETED
    final_view = SQLiteForgeMindState.open(database).get_task_view(task.task_id)
    assert final_view.current_status.status is TaskStatus.COMPLETED
    assert [item.action.action_type for item in final_view.actions] == [
        "tool_call",
        "tool_call",
        "tool_call",
        "tool_call",
        "complete",
    ]
