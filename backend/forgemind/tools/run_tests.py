"""run_tests 对 pytest JUnit XML 报告进行结构化解析。"""

from dataclasses import dataclass
from xml.etree import ElementTree

from forgemind.schema.run_tests import (
    RunTestsArguments,
    RunTestsResult,
    TestOutcome,
)


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
