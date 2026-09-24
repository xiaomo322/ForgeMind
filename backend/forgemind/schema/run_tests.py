"""run_tests 输入与结构化测试结果使用的严格数据契约。"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from forgemind.schema.base import StrictContractModel


DEFAULT_TEST_TIMEOUT_SECONDS = 120
MAX_TEST_TIMEOUT_SECONDS = 900

NonEmptyTestTarget = Annotated[str, Field(min_length=1)]


class TestOutcome(StrEnum):
    """pytest 已完成并产生可信报告后的测试业务结果。"""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    NO_TESTS = "no_tests"


class RunTestsArguments(StrictContractModel):
    """一次受控 pytest 请求的显式目标和超时。"""

    targets: tuple[NonEmptyTestTarget, ...] = Field(min_length=1)
    timeout_seconds: int = Field(
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        ge=1,
        le=MAX_TEST_TIMEOUT_SECONDS,
    )

    @field_validator("targets")
    @classmethod
    def reject_option_like_targets(
        cls,
        targets: tuple[str, ...],
    ) -> tuple[str, ...]:
        """目标是路径或 node id，不能成为额外 pytest 命令参数。"""

        # 第一步：逐项检查 target 是否以连字符开头。
        for target in targets:
            if target.startswith("-"):
                raise ValueError("测试目标不能是 pytest 命令选项")

        # 第二步：发现类似 -k、--config 的值时，前面已经抛出错误。

        # 第三步：所有目标安全时，原样返回不可变 tuple。
        return targets



class RunTestsResult(StrictContractModel):
    """pytest 已完成并且 JUnit XML 可解析时形成的真实结果。"""

    runner: Literal["pytest"]
    targets: tuple[NonEmptyTestTarget, ...] = Field(min_length=1)
    test_outcome: TestOutcome

    collected: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)
    skipped: int = Field(ge=0)

    exit_code: int
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str
    is_output_truncated: bool

    @model_validator(mode="after")
    def validate_result_consistency(self) -> Self:
        """拒绝统计数字与 test_outcome 互相矛盾的结果。"""

        # 第一步：确认四种分类数量之和等于 collected。
        classified_count = (
            self.passed
            + self.failed
            + self.errors
            + self.skipped
        )
        if classified_count != self.collected:
            raise ValueError("测试分类数量之和必须等于 collected")
        # 第二步：PASSED 要求至少收集一项，且 failed/errors 都为 0。
        if self.test_outcome is TestOutcome.PASSED:
            if self.collected == 0 or self.failed > 0 or self.errors > 0:
                raise ValueError("passed 结果必须实际收集测试且没有失败或错误")
        # 第三步：FAILED 要求 failed > 0，且 errors == 0。
        elif self.test_outcome is TestOutcome.FAILED:
            if self.failed == 0 or self.errors > 0:
                raise ValueError("failed 结果必须包含失败测试且不能包含错误")
        # 第四步：ERROR 要求 errors > 0。
        elif self.test_outcome is TestOutcome.ERROR:
            if self.errors == 0:
                raise ValueError("error 结果必须包含至少一个测试错误")
        # 第五步：NO_TESTS 要求 collected 和四种分类数量全部为 0。
        elif self.test_outcome is TestOutcome.NO_TESTS:
            if any(
                (
                    self.collected,
                    self.passed,
                    self.failed,
                    self.errors,
                    self.skipped,
                )
            ):
                raise ValueError("no_tests 结果的所有测试数量都必须为 0")

        # 第六步：核对 pytest 8.3 的公开退出码与业务结果一致。
        expected_exit_codes = {
            TestOutcome.PASSED: {0},
            TestOutcome.FAILED: {1},
            TestOutcome.ERROR: {1, 2, 3, 4},
            TestOutcome.NO_TESTS: {5},
        }
        if self.exit_code not in expected_exit_codes[self.test_outcome]:
            raise ValueError("pytest 退出码与 test_outcome 不一致")

        # 第七步：全部一致时返回 self。
        return self
