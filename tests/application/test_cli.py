import json
from pathlib import Path

from forgemind.cli import main


def test_cli_can_create_and_inspect_task_without_model_call(
    tmp_path: Path,
    capsys,
) -> None:
    database = tmp_path / "state.db"
    exit_code = main(
        [
            "--database",
            str(database),
            "start",
            "检查项目",
            "--project-root",
            str(tmp_path),
            "--no-run",
        ]
    )
    created = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert created["status"] == "running"

    exit_code = main(
        ["--database", str(database), "status", created["task_id"]]
    )
    restored = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert restored["task"]["original_request"] == "检查项目"
    assert restored["current_status"]["status"] == "running"
