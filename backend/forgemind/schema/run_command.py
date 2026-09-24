"""run_command 输入与已完成进程结果的严格数据契约。"""

import re
from typing import Annotated

from pydantic import Field, field_validator

from forgemind.schema.base import StrictContractModel


DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_TIMEOUT_SECONDS = 900
PROGRAM_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

NonEmptyText = Annotated[str, Field(min_length=1)]


class RunCommandArguments(StrictContractModel):
    """Agent 提出的程序别名、独立参数、项目内工作目录和超时。"""

    program: NonEmptyText
    args: tuple[str, ...] = ()
    working_directory: NonEmptyText
    timeout_seconds: int = Field(
        default=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        ge=1,
        le=MAX_COMMAND_TIMEOUT_SECONDS,
    )

    @field_validator("program")
    @classmethod
    def require_program_alias(cls, program: str) -> str:
        """program 只能是交给 Runtime 允许列表解析的逻辑别名。"""

        # 第一步：使用 PROGRAM_ALIAS_PATTERN.fullmatch 检查完整字符串。
        # 第二步：不匹配时抛出 ValueError；路径分隔符、盘符、空格和
        # Shell 元字符都不能成为 program alias 的一部分。
        if PROGRAM_ALIAS_PATTERN.fullmatch(program) is None:
            raise ValueError("program 必须是安全的程序别名")

        # 第三步：匹配成功时原样返回 program。
        return program


class RunCommandResult(StrictContractModel):
    """进程成功启动并在超时前结束后形成的真实结果。"""

    program: NonEmptyText
    executable: NonEmptyText
    args: tuple[str, ...]
    working_directory: NonEmptyText
    exit_code: int
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str
    is_output_truncated: bool
