from forgemind.runtime.acceptance import accept_read_file_decision
from forgemind.schema.decisions import ReadFileToolCallDecision


def test_runtime_accepts_decision_with_runtime_generated_ids() -> None:
    decision = ReadFileToolCallDecision.model_validate(
        {
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": "src/app.py"},
            "reason": "读取价格计算逻辑",
        }
    )
    generated_ids: list[str] = []

    def next_action_id() -> str:
        generated_ids.append("action-001")
        return "action-001"

    accepted = accept_read_file_decision(
        decision,
        task_id="task-001",
        next_action_id=next_action_id,
    )

    assert generated_ids == ["action-001"]
    assert accepted.action_id == "action-001"
    assert accepted.task_id == "task-001"
    assert accepted.arguments is decision.arguments
