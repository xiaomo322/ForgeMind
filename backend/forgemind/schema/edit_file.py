"""edit_file 输入与成功结果使用的严格数据契约。"""

from typing import Literal, Self

from pydantic import Field, model_validator

from forgemind.schema.base import StrictContractModel


class EditFileArguments(StrictContractModel):
    """一次 edit_file 请求经过校验后的完整参数。"""

    # 第一步：声明非空项目相对路径 path。
    path: str = Field(min_length=1)
    # 第二步：声明非空精确匹配文本 old_text。
    old_text: str = Field(min_length=1)
    # 第三步：声明必填 new_text；它允许空字符串表达明确删除。
    new_text: str
    # 第四步：声明非空 expected_version，修改必须绑定先前读取版本。
    expected_version: str = Field(min_length=1)


class EditFileResult(StrictContractModel):
    """edit_file 实际完成一次内容修改后的成功结果。"""

    # 第一步：声明非空 path、before_version 和 after_version。
    path: str = Field(min_length=1)
    before_version: str = Field(min_length=1)
    after_version: str = Field(min_length=1)
    # 第二步：replacement_count 在 V0.1 只能是字面值 1。
    replacement_count: Literal[1]
    # 第三步：diff 必须是非空字符串。
    diff: str = Field(min_length=1)
    # 第四步：模型字段校验后，再拒绝前后版本相同的伪成功结果。
    @model_validator(mode="after")
    def require_actual_version_change(self) -> Self:
        if self.before_version == self.after_version:
            raise ValueError(
                "edit_file 成功结果的前后版本不能相同"
            )

        return self

