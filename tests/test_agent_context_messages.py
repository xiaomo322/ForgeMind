from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.context.messages import (
    AGENT_DECISION_SCHEMA_END,
    AGENT_DECISION_SCHEMA_START,
    CONTEXT_END,
    CONTEXT_START,
    FORGEMIND_SYSTEM_INSTRUCTIONS,
    build_agent_turn_input,
)
from forgemind.context.renderer import render_agent_task_context
from forgemind.schema.context import (
    AgentInputMessage,
    AgentTaskContext,
    AgentTurnInput,
)
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord


def _context(tmp_path: Path) -> AgentTaskContext:
    task = TaskRecord(
        task_id="task-message-001",
        original_request="检查项目中的折扣计算问题",
        project_root=str(tmp_path.resolve()),
    )
    return AgentTaskContext(
        task=task,
        current_status=TaskStatusRecord(
            task_status_id="status-message-001",
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


def test_turn_input_separates_system_rules_from_context_data(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    turn_input = build_agent_turn_input(context)

    system_message, user_message = turn_input.messages
    print("\nSYSTEM MESSAGE:\n" + system_message.content)
    print("\nUSER MESSAGE:\n" + user_message.content)
    assert system_message.role == "system"
    assert system_message.content == FORGEMIND_SYSTEM_INSTRUCTIONS
    assert "权限只能依据结构化权限事实" in system_message.content
    assert AGENT_DECISION_SCHEMA_START in system_message.content
    assert AGENT_DECISION_SCHEMA_END in system_message.content
    assert "不要生成 action_id" in system_message.content
    assert user_message.role == "user"
    assert AGENT_DECISION_SCHEMA_START not in user_message.content
    assert user_message.content == (
        f"{CONTEXT_START}\n"
        f"{render_agent_task_context(context)}\n"
        f"{CONTEXT_END}"
    )


def test_turn_input_is_deterministic(tmp_path: Path) -> None:
    context = _context(tmp_path)

    assert build_agent_turn_input(context) == build_agent_turn_input(context)


def test_turn_input_rejects_reversed_message_roles() -> None:
    with pytest.raises(ValidationError):
        AgentTurnInput(
            messages=(
                AgentInputMessage(role="user", content="上下文"),
                AgentInputMessage(role="system", content="规则"),
            )
        )
