from pathlib import Path

import pytest

from forgemind.runtime.edit_file_execution import execute_edit_file_action
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.edit_file import EditFileWriteError


def make_registered_edit_action(
    *,
    path: str = "src/app.py",
    old_text: str = "discount = 1",
    new_text: str = "discount = 2",
    expected_content: bytes = b"discount = 1\n",
) -> tuple[AcceptedEditFileToolAction, InMemoryObservationRegistry]:
    actions = InMemoryActionRegistry()
    action = AcceptedEditFileToolAction(
        action_id="action-edit-flow-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": path,
            "old_text": old_text,
            "new_text": new_text,
            "expected_version": calculate_content_version(expected_content),
        },
        reason="修正折扣逻辑",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def test_execute_edit_file_records_real_success(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    initial = b"discount = 1\n"
    target.write_bytes(initial)
    action, observations = make_registered_edit_action(
        expected_content=initial
    )

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "success"
    assert target.read_bytes() == b"discount = 2\n"
    assert observation.result.before_version == calculate_content_version(
        initial
    )
    assert observation.result.after_version == calculate_content_version(
        target.read_bytes()
    )
    assert "-discount = 1" in observation.result.diff
    assert "+discount = 2" in observation.result.diff
    assert observations.get(action.action_id) is observation


def test_execute_edit_file_rejects_path_outside_project(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    action, observations = make_registered_edit_action(path="../outside.py")

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is ObservationErrorCode.PATH_OUTSIDE_PROJECT
    assert observations.get(action.action_id) is observation


def test_execute_edit_file_rejects_no_change_before_tool(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    action, observations = make_registered_edit_action(
        old_text="same",
        new_text="same",
    )

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is ObservationErrorCode.NO_CHANGE_REQUEST
    assert observations.get(action.action_id) is observation


def test_execute_edit_file_records_missing_file_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    action, observations = make_registered_edit_action()

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.FILE_NOT_FOUND
    assert observations.get(action.action_id) is observation


def test_execute_edit_file_records_version_failure(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"discount = 3\n")
    action, observations = make_registered_edit_action(
        expected_content=b"discount = 1\n"
    )

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.VERSION_MISMATCH
    assert target.read_bytes() == b"discount = 3\n"


def test_execute_edit_file_records_missing_target_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    content = b"price = 10\n"
    target.write_bytes(content)
    action, observations = make_registered_edit_action(
        expected_content=content
    )

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.EDIT_TARGET_NOT_FOUND
    assert target.read_bytes() == content


def test_execute_edit_file_records_ambiguous_target_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    content = b"discount = 1\ndiscount = 1\n"
    target.write_bytes(content)
    action, observations = make_registered_edit_action(
        expected_content=content
    )

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.EDIT_TARGET_AMBIGUOUS
    assert target.read_bytes() == content


def test_execute_edit_file_records_atomic_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    target = root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    initial = b"discount = 1\n"
    target.write_bytes(initial)
    action, observations = make_registered_edit_action(
        expected_content=initial
    )

    def fail_write(path: Path, prepared: object) -> None:
        raise EditFileWriteError(path, PermissionError("denied"))

    monkeypatch.setattr(
        "forgemind.runtime.edit_file_execution.replace_file_atomically",
        fail_write,
    )

    observation = execute_edit_file_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.FILE_WRITE_FAILED
    assert target.read_bytes() == initial
    assert observations.get(action.action_id) is observation
