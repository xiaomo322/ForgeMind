from pathlib import Path

import pytest

from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.runtime.search_code_execution import (
    SearchScopeCheckActionMismatchError,
    execute_search_code_action,
    record_search_scope_rejection,
)
from forgemind.schema.actions import AcceptedSearchCodeToolAction
from forgemind.schema.observations import ObservationErrorCode
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def make_registered_search_action(
    *,
    query: str = "discount",
    scope: str = ".",
) -> tuple[AcceptedSearchCodeToolAction, InMemoryObservationRegistry]:
    actions = InMemoryActionRegistry()
    action = AcceptedSearchCodeToolAction(
        action_id="action-search-flow-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="search_code",
        arguments={"query": query, "scope": scope},
        reason="定位相关代码",
    )
    actions.register(action)
    return action, InMemoryObservationRegistry(actions)


def test_execute_search_code_records_success(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("discount = 1\n", encoding="utf-8")
    action, observations = make_registered_search_action()

    observation = execute_search_code_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "success"
    assert observation.result.returned_count == 1
    assert observation.result.matches[0].path == "app.py"
    assert observations.get(action.action_id) is observation


def test_execute_search_code_records_zero_match_success(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("price = 1\n", encoding="utf-8")
    action, observations = make_registered_search_action()

    observation = execute_search_code_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "success"
    assert observation.result.matches == ()
    assert observation.result.is_complete is True
    assert observations.get(action.action_id) is observation


def test_execute_search_code_rejects_path_outside_project(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    action, observations = make_registered_search_action(scope="../outside")

    observation = execute_search_code_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is ObservationErrorCode.PATH_OUTSIDE_PROJECT
    assert observations.get(action.action_id) is observation


def test_execute_search_code_rejects_non_python_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("discount", encoding="utf-8")
    action, observations = make_registered_search_action(scope="README.md")

    observation = execute_search_code_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "rejected"
    assert observation.error.code is ObservationErrorCode.UNSUPPORTED_SEARCH_SCOPE
    assert observations.get(action.action_id) is observation


def test_execute_search_code_records_missing_scope_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    action, observations = make_registered_search_action(scope="missing")

    observation = execute_search_code_action(
        action,
        project_root=root,
        observations=observations,
    )

    assert observation.status == "failed"
    assert observation.error.code is ObservationErrorCode.SEARCH_SCOPE_NOT_FOUND
    assert observations.get(action.action_id) is observation


def test_scope_rejection_cannot_be_attached_to_another_action(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    action, observations = make_registered_search_action(scope="src")
    unrelated_failure = UnsafeProjectPathError(
        requested_path="../outside",
        project_root=root.resolve(),
        resolved_path=(tmp_path / "outside").resolve(),
    )

    with pytest.raises(SearchScopeCheckActionMismatchError):
        record_search_scope_rejection(
            action,
            unrelated_failure,
            observations=observations,
        )

    with pytest.raises(KeyError):
        observations.get(action.action_id)
