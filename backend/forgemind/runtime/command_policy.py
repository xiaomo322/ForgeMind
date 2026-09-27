"""解析 run_command 的程序允许列表与项目内工作目录。"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from forgemind.runtime.project_paths import resolve_project_path
from forgemind.schema.run_command import RunCommandArguments


class ProgramNotAllowedError(ValueError):
    """Agent 请求的程序别名不在当前 Runtime 允许列表中。"""

    def __init__(self, program: str) -> None:
        self.program = program
        super().__init__(f"程序未被允许：{program}")


class InvalidProgramPolicyError(ValueError):
    """Runtime 程序策略没有提供确定的绝对可执行文件路径。"""

    def __init__(self, program: str, executable: Path) -> None:
        self.program = program
        self.executable = executable
        super().__init__(f"程序策略无效：{program}")


@dataclass(frozen=True)
class ResolvedCommandContext:
    """Runtime 审核后交给 Tool 的确定程序、参数和工作目录。"""

    program: str
    executable: Path
    args: tuple[str, ...]
    working_directory: Path

    @property
    def command(self) -> tuple[str, ...]:
        """生成不经过 Shell 再解释的子进程参数元组。"""

        return (str(self.executable), *self.args)


def resolve_command_context(
    project_root: Path,
    arguments: RunCommandArguments,
    *,
    allowed_programs: Mapping[str, Path],
) -> ResolvedCommandContext:
    """根据 Runtime 允许列表和项目边界解析一次命令请求。"""

    # 第一步：用 arguments.program 查询 allowed_programs；不存在时抛出
    # ProgramNotAllowedError，并保存原 program 别名。
    try:
        executable = allowed_programs[arguments.program]
    except KeyError:
        raise ProgramNotAllowedError(
            arguments.program
        ) from None
    # 第二步：允许列表中的 executable 必须是绝对路径；否则抛出
    # InvalidProgramPolicyError。这里不检查文件是否存在。
    if not executable.is_absolute():
        raise InvalidProgramPolicyError(
            arguments.program,
            executable,
        )
    # 第三步：调用 resolve_project_path，把 working_directory 安全解析到
    # project_root 内。这里同样不检查目录是否已经存在。
    working_directory = resolve_project_path(
        project_root,
        arguments.working_directory,
    )
    # 第四步：原样保留 program 和 args，返回 ResolvedCommandContext。
    return ResolvedCommandContext(
        program=arguments.program,
        executable=executable,
        args=arguments.args,
        working_directory=working_directory,
    )
