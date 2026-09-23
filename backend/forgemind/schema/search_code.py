"""search_code 输入与结果使用的严格数据契约。"""

from pydantic import Field

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
