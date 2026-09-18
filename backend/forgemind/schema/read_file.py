from pydantic import Field

from forgemind.schema.base import StrictContractModel


# 这是 V0.1 的初始策略值。后续评测可以调整默认值，但不能绕过
# 字段契约，也不能允许 Agent 超出系统硬上限。
DEFAULT_READ_LINES = 200
MAX_READ_LINES = 1000


class ReadFileArguments(StrictContractModel):
    """一次 read_file 请求经过校验和缺省值规范化后的参数。"""

    # Schema 只检查字符串形状。Runtime 随后解析真实路径，并检查目标
    # 是否仍位于项目和授权范围内。
    path: str = Field(min_length=1)

    # 在模型中显式填入缺省值，使 AcceptedAction 可以记录 Tool 将收到的
    # 真实读取范围，而不是让 Tool 在执行时隐藏地选择默认值。
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=DEFAULT_READ_LINES, ge=1, le=MAX_READ_LINES)

    # 读取时版本可省略；一旦提供就不能为空。它是否与当前文件匹配，
    # 属于 Runtime 的动态事实检查，不属于纯 Schema 校验。
    expected_version: str | None = Field(default=None, min_length=1)


class ReadFileResult(StrictContractModel):
    """read_file 从同一已验证文本快照返回的实际行范围。"""

    path: str = Field(min_length=1)
    content: str
    start_line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)
    returned_lines: int = Field(ge=0)
    eof: bool
    version: str = Field(min_length=1)
    is_truncated: bool
