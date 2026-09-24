"""run_tests 对 pytest JUnit XML 报告进行结构化解析。"""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic_ns
from xml.etree import ElementTree

from forgemind.runtime.run_tests_targets import ResolvedTestTarget
from forgemind.schema.run_tests import (
    RunTestsArguments,
    RunTestsResult,
    TestOutcome,
)


MAX_TEST_OUTPUT_BYTES = 64 * 1024
MAX_JUNIT_XML_BYTES = 4 * 1024 * 1024


class InvalidPytestReportError(ValueError):
    """pytest 报告缺失必要结构、属性或一致统计。"""


@dataclass(frozen=True)
class PytestReportCounts:
    """从一个完整 JUnit XML 报告汇总出的测试数量。"""

    collected: int
    passed: int
    failed: int
    errors: int
    skipped: int


class RunTestsToolError(RuntimeError):
    """run_tests 未能取得完整、可信测试结果的共同错误。"""


class RunTestsTargetMismatchError(RunTestsToolError):
    """安全解析后的测试目标与已接受参数不一致。"""


class PytestProcessStartError(RunTestsToolError):
    """操作系统未能启动 pytest 进程。"""

    def __init__(self, cause: OSError) -> None:
        self.error_type = type(cause).__name__
        super().__init__("操作系统未能启动 pytest")


class PytestProcessTimeoutError(RunTestsToolError):
    """pytest 在允许时间内没有完成。"""

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
        super().__init__("pytest 执行超时")


class PytestReportUnavailableError(RunTestsToolError):
    """pytest 已结束，但没有产生可读取的 JUnit XML。"""

    def __init__(
        self,
        *,
        exit_code: int,
        duration_ms: int,
        stdout: str,
        stderr: str,
        is_output_truncated: bool,
    ) -> None:
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.stdout = stdout
        self.stderr = stderr
        self.is_output_truncated = is_output_truncated
        super().__init__("pytest 没有产生 JUnit XML 报告")


class PytestReportTooLargeError(RunTestsToolError):
    """JUnit XML 超过 V0.1 允许解析的字节上限。"""

    def __init__(self, *, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__("pytest JUnit XML 报告超过字节上限")


def _read_bounded_text(path: Path) -> tuple[str, bool]:
    """最多读取输出上限加一字节，并返回 UTF-8 替换解码文本。"""

    with path.open("rb") as stream:
        content = stream.read(MAX_TEST_OUTPUT_BYTES + 1)
    is_truncated = len(content) > MAX_TEST_OUTPUT_BYTES
    return (
        content[:MAX_TEST_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        is_truncated,
    )


def _read_junit_xml(path: Path) -> bytes:
    """只在完整报告未超过硬上限时返回 XML 字节。"""

    with path.open("rb") as stream:
        content = stream.read(MAX_JUNIT_XML_BYTES + 1)
    if len(content) > MAX_JUNIT_XML_BYTES:
        raise PytestReportTooLargeError(max_bytes=MAX_JUNIT_XML_BYTES)
    return content


def parse_pytest_junit_counts(junit_xml: bytes) -> PytestReportCounts:
    """解析 pytest JUnit XML，并汇总顶层 testsuite 统计。"""

    # 第一步：用 ElementTree.fromstring 解析字节；格式错误转换为领域错误。
    try:
        root = ElementTree.fromstring(junit_xml)
    except ElementTree.ParseError as exc:
        raise InvalidPytestReportError("JUnit XML 格式无效") from exc
    # 第二步：兼容根元素 testsuite，或 testsuites 下的直接 testsuite 子项。
    if root.tag == "testsuite":
        suites = (root,)
    elif root.tag == "testsuites":
        # 只读取直接子节点，避免重复统计嵌套的 testsuite。
        suites = tuple(root.findall("testsuite"))
    # 第三步：没有 testsuite 时，抛出 InvalidPytestReportError。
    else:
        raise InvalidPytestReportError("JUnit XML 根元素不受支持")
    if not suites:
        raise InvalidPytestReportError("JUnit XML 中没有 testsuite")

    # 第四步：逐个读取 tests/failures/errors/skipped 必填属性并转成整数。
    collected = 0
    failed = 0
    errors = 0
    skipped = 0
    # 第五步：属性缺失、不是整数或出现负数时，转换为领域错误。
    try:
        for suite in suites:
            suite_collected = int(suite.attrib["tests"])
            suite_failed = int(suite.attrib["failures"])
            suite_errors = int(suite.attrib["errors"])
            suite_skipped = int(suite.attrib["skipped"])

            suite_counts = (
                suite_collected,
                suite_failed,
                suite_errors,
                suite_skipped,
            )
            if min(suite_counts) < 0:
                raise ValueError

            collected += suite_collected
            failed += suite_failed
            errors += suite_errors
            skipped += suite_skipped
    except (KeyError, ValueError) as exc:
        raise InvalidPytestReportError(
            "JUnit XML 测试统计无效"
        ) from exc

    passed = collected - failed - errors - skipped
    if passed < 0:
        raise InvalidPytestReportError(
            "JUnit XML 测试统计互相矛盾"
        )

    return PytestReportCounts(
        collected=collected,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
    )


def build_run_tests_result_from_junit(
    arguments: RunTestsArguments,
    *,
    junit_xml: bytes,
    exit_code: int,
    duration_ms: int,
    stdout: str,
    stderr: str,
    is_output_truncated: bool,
) -> RunTestsResult:
    """把完整 pytest 报告和实际进程事实构造成严格结果。"""

    counts = parse_pytest_junit_counts(junit_xml)
    if counts.collected == 0:
        outcome = TestOutcome.NO_TESTS
    elif counts.errors > 0:
        outcome = TestOutcome.ERROR
    elif counts.failed > 0:
        outcome = TestOutcome.FAILED
    else:
        outcome = TestOutcome.PASSED

    return RunTestsResult(
        runner="pytest",
        targets=arguments.targets,
        test_outcome=outcome,
        collected=counts.collected,
        passed=counts.passed,
        failed=counts.failed,
        errors=counts.errors,
        skipped=counts.skipped,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        is_output_truncated=is_output_truncated,
    )


def run_pytest(
    project_root: Path,
    arguments: RunTestsArguments,
    resolved_targets: tuple[ResolvedTestTarget, ...],
) -> RunTestsResult:
    """在受控子进程中运行 pytest，并返回完整 JUnit 结果。"""

    # 第一步：比较 resolved_targets 中的 requested_target 与
    # arguments.targets；不一致时抛出 RunTestsTargetMismatchError。
    requested_targets = tuple(
        target.requested_target
        for target in resolved_targets
    )
    if requested_targets != arguments.targets:
        raise RunTestsTargetMismatchError(
            "安全解析后的测试目标与原参数不一致"
        )

    # 第二步：创建本次执行专属的 TemporaryDirectory，并准备
    # report.xml、stdout.log、stderr.log 和 pytest-temp 路径。
    with tempfile.TemporaryDirectory(
        prefix="forgemind-run-tests-",
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        report_path = temporary_root / "report.xml"
        stdout_path = temporary_root / "stdout.log"
        stderr_path = temporary_root / "stderr.log"
        pytest_temp_path = temporary_root / "pytest-temp"
    # 第三步：构造不可变命令 tuple。固定部分依次为：
    # sys.executable、-m、pytest、-q、--color=no、--tb=short、
    # -p、no:cacheprovider、--junitxml=<报告路径>、
    # --basetemp=<临时路径>；最后追加每个 target.command_argument。

        command = (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--color=no",
            "--tb=short",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report_path}",
            f"--basetemp={pytest_temp_path}",
            *(
                target.command_argument
                for target in resolved_targets
            ),
        )
        # 第四步：记录 monotonic_ns 起点，以二进制写模式打开 stdout/stderr；
        # 调用 subprocess.run，传入 cwd=project_root.resolve()、
        # stdout/stderr 文件、timeout、check=False、shell=False。
        started_at = monotonic_ns()

        try:
            with (
                stdout_path.open("wb") as stdout_stream,
                stderr_path.open("wb") as stderr_stream,
            ):
                completed_process = subprocess.run(
                    command,
                    cwd=project_root.resolve(),
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    timeout=arguments.timeout_seconds,
                    check=False,
                    shell=False,
                )
        except subprocess.TimeoutExpired as exc:
            duration_ms = (
                monotonic_ns() - started_at
            ) // 1_000_000

            stdout, stdout_truncated = _read_bounded_text(
                stdout_path
            )
            stderr, stderr_truncated = _read_bounded_text(
                stderr_path
            )

            raise PytestProcessTimeoutError(
                timeout_seconds=arguments.timeout_seconds,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
                is_output_truncated=(
                    stdout_truncated or stderr_truncated
                ),
            ) from exc
        # 第五步：OSError 转为 PytestProcessStartError；TimeoutExpired 时先计算
        # duration_ms，再读取已经落盘的有限输出，抛出 PytestProcessTimeoutError。
        except OSError as exc:
            raise PytestProcessStartError(exc) from exc

        duration_ms = (
            monotonic_ns() - started_at
        ) // 1_000_000

        stdout, stdout_truncated = _read_bounded_text(
            stdout_path
        )
        stderr, stderr_truncated = _read_bounded_text(
            stderr_path
        )
        is_output_truncated = (
            stdout_truncated or stderr_truncated
        )
        # 第六步：正常结束后计算 duration_ms，读取 stdout/stderr，并把任一
        # 输出被截断合并成一个 is_output_truncated 标志。
        if not report_path.is_file():
            raise PytestReportUnavailableError(
                exit_code=completed_process.returncode,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
                is_output_truncated=is_output_truncated,
            )

        # 第七步：report.xml 不存在或不是普通文件时，携带真实进程事实抛出
        # PytestReportUnavailableError；存在时用 _read_junit_xml 受限读取。
        junit_xml = _read_junit_xml(report_path)

        # 第八步：调用 build_run_tests_result_from_junit，传入原 arguments、
        # XML、真实 returncode、耗时、输出和截断标志，返回严格结果。

        return build_run_tests_result_from_junit(
            arguments,
            junit_xml=junit_xml,
            exit_code=completed_process.returncode,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            is_output_truncated=is_output_truncated,
        )
