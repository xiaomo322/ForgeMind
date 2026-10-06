import pytest
from pydantic import ValidationError

from forgemind.schema.execution import EditExecutionPlan


def _plan(**changes: str) -> EditExecutionPlan:
    values = {
        "action_id": "action-edit-001",
        "task_id": "task-001",
        "path": "app.py",
        "before_version": "sha256:before",
        "after_version": "sha256:after",
        "diff": "--- app.py\n+++ app.py\n@@\n-old\n+new\n",
    }
    values.update(changes)
    return EditExecutionPlan(**values)


def test_edit_execution_plan_is_strict_and_immutable() -> None:
    plan = _plan()

    with pytest.raises(ValidationError):
        EditExecutionPlan(**plan.model_dump(), extra_field="forbidden")
    with pytest.raises(ValidationError):
        plan.path = "other.py"


def test_edit_execution_plan_requires_distinct_versions() -> None:
    with pytest.raises(ValidationError):
        _plan(after_version="sha256:before")


@pytest.mark.parametrize(
    "field_name",
    ["action_id", "task_id", "path", "before_version", "after_version", "diff"],
)
def test_edit_execution_plan_rejects_blank_text(field_name: str) -> None:
    with pytest.raises(ValidationError):
        _plan(**{field_name: "   "})
