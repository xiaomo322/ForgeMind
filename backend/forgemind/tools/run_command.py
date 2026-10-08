"""在受控工作目录中执行 Runtime 已解析的程序和参数。"""

from pathlib import Path
import subprocess
import tempfile
from time import monotonic_ns

from forgemind.runtime.command_policy import ResolvedCommandContext
from forgemind.schema.run_command import RunCommandResult
from forgemind.tools.process_environment import (
    build_safe_process_environment,
    redact_process_temporary_path,
)


MAX_COMMAND_OUTPUT_BYTES = 64 * 1024


class RunCommandToolError(RuntimeError):
    """run_command 未能取得完整进程结果的共同错误。"""


class CommandProcessStartError(RunCommandToolError):
    """操作系统未能启动已解析的程序。"""

    def __init__(self, cause: OSError) -> None:
        self.error_type = type(cause).__name__
        super().__init__("操作系统未能启动命令")


class CommandProcessTimeoutError(RunCommandToolError):
    """命令在允许时间内没有结束。"""

    def __init__(
        self,
        *,
        timeout_seconds: int,
        duration_ms: int,
        stdout: str,
        stderr: str,
        is_output_truncated: bool,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.duration_ms = duration_ms
        self.stdout = stdout
        self.stderr = stderr
        self.is_output_truncated = is_output_truncated
        super().__init__("命令执行超时")


def _read_bounded_text(path: Path) -> tuple[str, bool]:
    """只把有限输出返回给 Agent，并标明是否还有内容未返回。"""

    with path.open("rb") as stream:
        content = stream.read(MAX_COMMAND_OUTPUT_BYTES + 1)
    is_truncated = len(content) > MAX_COMMAND_OUTPUT_BYTES
    return (
        content[:MAX_COMMAND_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        is_truncated,
    )


def run_command_process(
    context: ResolvedCommandContext,
    *,
    timeout_seconds: int,
) -> RunCommandResult:
    """执行已经过 Runtime 审核的命令，并返回真实完成事实。"""

    with tempfile.TemporaryDirectory(
        prefix="forgemind-run-command-",
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        stdout_path = temporary_root / "stdout.log"
        stderr_path = temporary_root / "stderr.log"

        # 第一步：用 monotonic_ns 记录开始时间。
        started_at = monotonic_ns()
        # 第二步：以二进制写模式打开 stdout/stderr 临时文件。
        try:
            with (
                stdout_path.open("wb") as stdout_stream,
                stderr_path.open("wb") as stderr_stream,
            ):
                # 第三步：调用 subprocess.run：
                # - 第一个参数必须是 context.command，而不是拼接的字符串；
                # - cwd 使用 context.working_directory；
                # - timeout 使用本函数参数；
                # - check=False，非零退出码也是有效完成事实；
                # - shell=False，不让 Shell 再解释 args。
                completed_process = subprocess.run(
                    context.command,
                    cwd=context.working_directory,
                    env=build_safe_process_environment(temporary_root),
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    timeout=timeout_seconds,
                    check=False,
                    shell=False,
                )
        # 第四步：TimeoutExpired 时计算耗时、读取有限输出，并抛出
        # CommandProcessTimeoutError；OSError 转成 CommandProcessStartError。
        except subprocess.TimeoutExpired as exc:
            duration_ms = (monotonic_ns() - started_at) // 1_000_000
            stdout, stdout_truncated = _read_bounded_text(stdout_path)
            stderr, stderr_truncated = _read_bounded_text(stderr_path)
            stdout = redact_process_temporary_path(stdout, temporary_root)
            stderr = redact_process_temporary_path(stderr, temporary_root)

            raise CommandProcessTimeoutError(
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
                is_output_truncated=stdout_truncated or stderr_truncated,
            ) from exc
        except OSError as exc:
            raise CommandProcessStartError(exc) from exc
        # 第五步：正常结束时计算耗时和有限输出，构造 RunCommandResult。
        duration_ms = (monotonic_ns() - started_at) // 1_000_000
        stdout, stdout_truncated = _read_bounded_text(stdout_path)
        stderr, stderr_truncated = _read_bounded_text(stderr_path)
        stdout = redact_process_temporary_path(stdout, temporary_root)
        stderr = redact_process_temporary_path(stderr, temporary_root)
        return RunCommandResult(
            program=context.program,
            executable=str(context.executable),
            args=context.args,
            working_directory=str(context.working_directory),
            exit_code=completed_process.returncode,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            is_output_truncated=stdout_truncated or stderr_truncated,
        )
