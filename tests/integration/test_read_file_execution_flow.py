from pathlib import Path

from forgemind.runtime.read_file_execution import execute_read_file_action
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def make_registered_action(
    *,
    path: str,
    expected_content: bytes,
    start_line: int = 1,
) -> tuple[AcceptedReadFileToolAction, InMemoryObservationRegistry]:
    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-read-flow-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": path,
            "start_line": start_line,
            "expected_version": calculate_content_version(expected_content),
        },
        reason="读取项目文件",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def test_execute_read_file_records_success_from_real_project_file(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    target = project_root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    content = b"first line\nsecond line\n"
    target.write_bytes(content)
    action, observations = make_registered_action(
        path="src/app.py",
        expected_content=content,
    )

    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )

    assert observation.status == "success"
    assert observation.result.content == "first line\nsecond line\n"
    assert observations.get(action.action_id) is observation


def test_execute_unversioned_first_read_establishes_actual_version(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    target = project_root / "src" / "first_read.py"
    target.parent.mkdir(parents=True)
    content = b"first observed content\n"
    target.write_bytes(content)

    actions = InMemoryActionRegistry()
    action = AcceptedReadFileToolAction(
        action_id="action-first-read-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={"path": "src/first_read.py"},
        reason="首次读取文件并建立版本",
    )
    actions.register(action)
    observations = InMemoryObservationRegistry(actions)

    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )

    assert observation.status == "success"
    assert observation.result.content == "first observed content\n"
    assert observation.result.version == calculate_content_version(content)
    assert observations.get(action.action_id) is observation


def test_execute_read_file_rejects_path_outside_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    action, observations = make_registered_action(
        path="../outside.py",
        expected_content=b"outside",
    )

    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is ObservationErrorCode.PATH_OUTSIDE_PROJECT
    assert observations.get(action.action_id) is observation


def test_execute_read_file_records_missing_file_failure(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    action, observations = make_registered_action(
        path="src/missing.py",
        expected_content=b"",
    )

    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.FILE_NOT_FOUND
    assert observations.get(action.action_id) is observation


def test_execute_read_file_records_snapshot_version_failure(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    target = project_root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new content\n")
    action, observations = make_registered_action(
        path="src/app.py",
        expected_content=b"old content\n",
    )

    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.VERSION_MISMATCH
    assert observations.get(action.action_id) is observation


def test_execute_read_file_records_text_processing_failure(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    target = project_root / "src" / "binary.py"
    target.parent.mkdir(parents=True)
    content = b"\xff"
    target.write_bytes(content)
    action, observations = make_registered_action(
        path="src/binary.py",
        expected_content=content,
    )

    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.INVALID_TEXT_ENCODING
    assert observations.get(action.action_id) is observation
