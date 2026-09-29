import pytest

from forgemind.schema.actions import (
    AcceptedAskUserAction,
    AcceptedReadFileToolAction,
    SequencedActionRecord,
)
from forgemind.state.action_registry import (
    DuplicateActionIdError,
    InMemoryActionRegistry,
)


def _ask_action(action_id: str = "action-shared-001") -> AcceptedAskUserAction:
    return AcceptedAskUserAction(
        action_id=action_id,
        task_id="task-001",
        action_type="ask_user",
        reason="缺少业务规则",
        question="折扣可以叠加吗？",
        options=("可以", "不可以"),
    )


def _tool_action(
    action_id: str = "action-tool-001",
) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
        reason="读取价格逻辑",
    )


def test_in_memory_registry_stores_ask_user_action() -> None:
    registry = InMemoryActionRegistry()
    action = _ask_action()

    registry.register(action)

    assert registry.get(action.action_id) is action


def test_tool_and_ask_user_actions_share_one_id_namespace() -> None:
    registry = InMemoryActionRegistry()
    original = _tool_action(action_id="action-shared-001")
    registry.register(original)

    with pytest.raises(DuplicateActionIdError):
        registry.register(_ask_action(action_id="action-shared-001"))

    assert registry.get("action-shared-001") is original


def test_sequenced_record_accepts_ask_user_action() -> None:
    action = _ask_action()

    record = SequencedActionRecord(sequence=1, action=action)

    assert record.action == action
