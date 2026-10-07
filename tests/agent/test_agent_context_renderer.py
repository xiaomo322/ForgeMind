import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.context.renderer import render_agent_task_context
from forgemind.schema.context import AgentContextEnvelope, AgentTaskContext
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord


def _context(tmp_path: Path) -> AgentTaskContext:
    task = TaskRecord(
        task_id="task-render-001",
        original_request="修复会员折扣没有生效的问题",
        project_root=str(tmp_path.resolve()),
    )
    return AgentTaskContext(
        task=task,
        current_status=TaskStatusRecord(
            task_status_id="status-render-001",
            task_id=task.task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
        recent_actions=(),
        total_action_count=0,
        omitted_action_count=0,
        is_action_history_complete=True,
    )


def test_renderer_emits_versioned_json_with_unescaped_chinese(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    rendered = render_agent_task_context(context)
    print(f"\n真实 Agent Context JSON：\n{rendered}")
    payload = json.loads(rendered)

    assert payload["schema_version"] == "0.1"
    assert payload["context_type"] == "task_context"
    assert payload["context"]["task"]["original_request"] == (
        "修复会员折扣没有生效的问题"
    )
    assert "修复会员折扣没有生效的问题" in rendered
    assert "\\u4fee" not in rendered


def test_renderer_is_deterministic_for_same_context(tmp_path: Path) -> None:
    context = _context(tmp_path)

    first = render_agent_task_context(context)
    second = render_agent_task_context(context)

    assert first == second


def test_envelope_rejects_unknown_schema_version(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        AgentContextEnvelope(
            schema_version="0.2",  # type: ignore[arg-type]
            context=_context(tmp_path),
        )
