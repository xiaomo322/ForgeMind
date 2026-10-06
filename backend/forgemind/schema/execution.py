"""Runtime 跨进程恢复外部副作用所需的持久化执行计划。"""

from typing import Self

from pydantic import Field, field_validator, model_validator

from forgemind.schema.base import StrictContractModel


class EditExecutionPlan(StrictContractModel):
    """已批准 edit_file 在真正写盘前保存的不可变对账依据。"""

    action_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    before_version: str = Field(min_length=1)
    after_version: str = Field(min_length=1)
    diff: str = Field(min_length=1)

    @field_validator(
        "action_id",
        "task_id",
        "path",
        "before_version",
        "after_version",
        "diff",
    )
    @classmethod
    def require_visible_text(cls, value: str) -> str:
        """索引和对账字段不能只由空白字符组成。"""

        if not value.strip():
            raise ValueError("执行计划字段不能只包含空白字符")
        return value

    @model_validator(mode="after")
    def require_actual_change(self) -> Self:
        """修改前后版本相同不能表示一次真实文件变更。"""

        if self.before_version == self.after_version:
            raise ValueError("修改前后文件版本必须不同")
        return self
