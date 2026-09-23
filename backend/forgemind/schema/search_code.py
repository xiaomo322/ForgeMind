"""search_code 输入与结果使用的严格数据契约。"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from forgemind.schema.base import StrictContractModel


# 默认值属于公开协议的一部分：Agent 省略字段时，Runtime 仍能在
# AcceptedAction 中记录 Tool 将实际使用的确定值。
DEFAULT_SEARCH_RESULTS = 20
MAX_SEARCH_RESULTS = 100


class SearchCodeArguments(StrictContractModel):
    """一次 search_code 请求经过校验和缺省值规范化后的参数。"""

    # 第一步：声明必填 query，只验证它是非空字符串。
    query: str = Field(min_length=1)
    # 是否能找到相关代码属于 Tool 的执行结果，不能由 Schema 猜测。
    # 第二步：声明 scope，默认值是项目根目录的相对表示 "."。
    scope: str = Field(
        default=".",
        min_length=1,
    )
    # 是否在项目根目录内由 Runtime 结合真实 project_root 检查。
    # 第三步：声明 max_results，默认 20，并限制在 1～100。
    max_results: int = Field(
        default=DEFAULT_SEARCH_RESULTS,
        ge=1,
        le=MAX_SEARCH_RESULTS,
    )


class SearchIncompleteReason(StrEnum):
    """search_code 成功执行但结果未完整覆盖的稳定原因。"""

    RESULT_LIMIT_REACHED = "RESULT_LIMIT_REACHED"
    FILE_SKIPPED = "FILE_SKIPPED"


class SearchCodeMatch(StrictContractModel):
    """search_code 实际返回的一条字面文本命中。"""

    # 第一步：声明非空项目相对路径 path。
    path: str = Field(min_length=1)

    # 第二步：声明从 1 开始的 line_number。
    line_number: int = Field(ge=1)

    # 第三步：声明实际匹配行 line_text；空字符串也保留为字符串类型，
    # 是否真的包含 query 由 Tool 构造结果时保证。
    line_text: str


class SearchCodeResult(StrictContractModel):
    """一次成功 search_code 调用取得的实际结果。"""

    # 第一步：声明原 query、实际 searched_scope 和不可变 matches。
    query: str = Field(min_length=1)
    searched_scope: str = Field(min_length=1)
    matches: tuple[SearchCodeMatch, ...]

    # 第二步：声明 returned_count、is_complete 和不可变原因集合。
    returned_count: int = Field(ge=0)
    is_complete: bool
    incomplete_reasons: tuple[SearchIncompleteReason, ...]

    # 第三步：使用 after validator 检查 returned_count 等于 matches 长度。
    @model_validator(mode="after")
    def validate_result_consistency(self) -> Self:
        if self.returned_count != len(self.matches):
            raise ValueError(
                "returned_count 必须等于 matches 数量"
            )

        # 第四步：完整结果必须没有原因；不完整结果必须至少有一个原因。
        if self.is_complete and self.incomplete_reasons:
            raise ValueError(
                "完整结果不能包含 incomplete_reasons"
            )

        if not self.is_complete and not self.incomplete_reasons:
            raise ValueError(
                "不完整结果必须说明原因"
            )

        return self
