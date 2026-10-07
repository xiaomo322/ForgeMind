"""验证 State 使用完 SQLite 后不会遗留数据库文件锁。"""

from pathlib import Path

from forgemind.state.sqlite_state import SQLiteForgeMindState


def test_opening_state_does_not_keep_database_file_locked(
    tmp_path: Path,
) -> None:
    """State 初始化完成后，Windows 应能立即删除数据库文件。"""

    database_path = tmp_path / "state.db"

    SQLiteForgeMindState.open(database_path)

    # Windows 只要仍有 sqlite3.Connection 未关闭，这里就会抛出
    # PermissionError。测试因此直接覆盖此前 TemporaryDirectory 的故障。
    database_path.unlink()

    assert not database_path.exists()
