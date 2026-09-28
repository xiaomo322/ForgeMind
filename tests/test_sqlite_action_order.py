from pathlib import Path

from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.read_file import ReadFileArguments
from forgemind.schema.tasks import TaskRecord, TaskStatus, TaskStatusRecord
from forgemind.state.sqlite_state import SQLiteForgeMindState


def _create_task(
    state: SQLiteForgeMindState,
    project_root: Path,
    task_id: str,
) -> None:
    state.create_task(
        TaskRecord(
            task_id=task_id,
            original_request=f"处理 {task_id}",
            project_root=str(project_root.resolve()),
        ),
        TaskStatusRecord(
            task_status_id=f"status-{task_id}",
            task_id=task_id,
            revision=1,
            status=TaskStatus.RUNNING,
            reason="任务创建",
        ),
    )


def _action(action_id: str, task_id: str) -> AcceptedReadFileToolAction:
    return AcceptedReadFileToolAction(
        action_id=action_id,
        task_id=task_id,
        action_type="tool_call",
        tool_name="read_file",
        arguments=ReadFileArguments(
            path=f"{action_id}.py",
            start_line=1,
            max_lines=20,
        ),
        reason=f"读取 {action_id}",
    )


def test_actions_use_registration_order_instead_of_action_id_order(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.db"
    state = SQLiteForgeMindState.open(database_path)
    _create_task(state, tmp_path, "task-001")
    first = _action("z-last-lexically", "task-001")
    second = _action("a-first-lexically", "task-001")
    state.actions.register(first)
    state.actions.register(second)

    restored = SQLiteForgeMindState.open(database_path).actions.list_for_task(
        "task-001"
    )

    assert [item.sequence for item in restored] == [1, 2]
    assert [item.action for item in restored] == [first, second]


def test_action_sequence_starts_at_one_for_each_task(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    _create_task(state, tmp_path, "task-001")
    _create_task(state, tmp_path, "task-002")
    task_one_action = _action("action-task-one", "task-001")
    task_two_action = _action("action-task-two", "task-002")
    state.actions.register(task_one_action)
    state.actions.register(task_two_action)

    task_one = state.actions.list_for_task("task-001")
    task_two = state.actions.list_for_task("task-002")

    assert task_one[0].sequence == 1
    assert task_one[0].action == task_one_action
    assert task_two[0].sequence == 1
    assert task_two[0].action == task_two_action


def test_task_without_actions_has_empty_ordered_history(tmp_path: Path) -> None:
    state = SQLiteForgeMindState.open(tmp_path / "state.db")
    _create_task(state, tmp_path, "task-001")

    assert state.actions.list_for_task("task-001") == ()
