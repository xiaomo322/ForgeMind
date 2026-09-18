import pytest

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.state.action_registry import (
    DuplicateActionIdError,
    InMemoryActionRegistry,
)


def _accepted_action(action_id: str, path: str) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction.model_validate(
        {
            "action_id": action_id,
            "task_id": "task-001",
            "action_type": "tool_call",
            "tool_name": "read_file",
            "arguments": {"path": path},
            "reason": "读取目标文件",
        }
    )


def test_registry_rejects_duplicate_id_without_overwriting_original() -> None:
    registry = InMemoryActionRegistry()
    original = _accepted_action("action-001", "src/original.py")
    duplicate = _accepted_action("action-001", "src/replacement.py")
    registry.register(original)

    with pytest.raises(DuplicateActionIdError):
        registry.register(duplicate)

    assert registry.get("action-001") is original
    assert registry.get("action-001").arguments.path == "src/original.py"
