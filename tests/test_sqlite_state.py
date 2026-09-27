from pathlib import Path

from forgemind.schema.tasks import TaskRecord
from forgemind.state.sqlite_action_registry import SQLiteActionRegistry
from forgemind.state.sqlite_observation_registry import (
    SQLiteObservationRegistry,
)
from forgemind.state.sqlite_permission_decision_registry import (
    SQLitePermissionDecisionRegistry,
)
from forgemind.state.sqlite_permission_request_registry import (
    SQLitePermissionRequestRegistry,
)
from forgemind.state.sqlite_state import SQLiteForgeMindState
from forgemind.state.sqlite_task_registry import SQLiteTaskRegistry


def test_open_builds_complete_state_for_one_database(tmp_path: Path) -> None:
    """统一入口应建立数据库和全部四个 SQLite Registry。"""

    database_path = tmp_path / "nested" / "state.db"

    state = SQLiteForgeMindState.open(database_path)

    assert state.database_path == database_path.resolve()
    assert database_path.is_file()
    assert isinstance(state.tasks, SQLiteTaskRegistry)
    assert isinstance(state.actions, SQLiteActionRegistry)
    assert isinstance(
        state.permission_requests,
        SQLitePermissionRequestRegistry,
    )
    assert isinstance(
        state.permission_decisions,
        SQLitePermissionDecisionRegistry,
    )
    assert isinstance(state.observations, SQLiteObservationRegistry)

    task = TaskRecord(
        task_id="task-001",
        original_request="修复会员折扣没有生效的问题",
        project_root=str(tmp_path.resolve()),
    )
    state.tasks.register(task)

    assert SQLiteForgeMindState.open(database_path).tasks.get(task.task_id) == task


def test_reopen_builds_fresh_registry_objects(tmp_path: Path) -> None:
    """重启后应重建 Registry 对象，而不是依赖旧内存对象。"""

    database_path = tmp_path / "state.db"
    first = SQLiteForgeMindState.open(database_path)

    reopened = SQLiteForgeMindState.open(database_path)

    assert reopened.database_path == first.database_path
    assert reopened is not first
    assert reopened.tasks is not first.tasks
    assert reopened.actions is not first.actions
    assert reopened.permission_requests is not first.permission_requests
    assert reopened.permission_decisions is not first.permission_decisions
    assert reopened.observations is not first.observations
