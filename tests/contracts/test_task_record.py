from pathlib import Path

import pytest
from pydantic import ValidationError

from forgemind.schema.tasks import TaskRecord


def test_task_record_preserves_creation_facts(tmp_path: Path) -> None:
    """TaskRecord 保留用户原话，并绑定绝对项目根目录。"""

    original_request = "  修复会员折扣没有生效的问题\n"
    project_root = str(tmp_path.resolve())

    task = TaskRecord(
        task_id="task-001",
        original_request=original_request,
        project_root=project_root,
    )

    assert task.task_id == "task-001"
    assert task.original_request == original_request
    assert task.project_root == project_root


@pytest.mark.parametrize(
    "field_name",
    ["task_id", "original_request", "project_root"],
)
def test_task_record_rejects_whitespace_only_text(
    tmp_path: Path,
    field_name: str,
) -> None:
    """必填来源字段不能使用看似非空的空白字符串。"""

    values = {
        "task_id": "task-001",
        "original_request": "修复会员折扣",
        "project_root": str(tmp_path.resolve()),
    }
    values[field_name] = " \n\t "

    with pytest.raises(ValidationError):
        TaskRecord(**values)


def test_task_record_rejects_relative_project_root() -> None:
    """重启后不能让同一任务随当前工作目录漂移到另一项目。"""

    with pytest.raises(ValidationError):
        TaskRecord(
            task_id="task-001",
            original_request="修复会员折扣",
            project_root="projects/shop",
        )
