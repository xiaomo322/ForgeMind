from enum import StrEnum

from pydantic import ValidationError

from forgemind.schema.base import StrictContractModel


class SchemaErrorCode(StrEnum):
    """供 Agent 和 Runtime 使用的 ForgeMind 稳定错误码。"""

    MISSING_FIELD = "MISSING_FIELD"
    INVALID_TYPE = "INVALID_TYPE"
    INVALID_VALUE = "INVALID_VALUE"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    INVALID_COMBINATION = "INVALID_COMBINATION"


class SchemaValidationError(StrictContractModel):
    """Agent 决策校验中发现的一条规范化问题。"""

    code: SchemaErrorCode
    message: str
    field_path: tuple[str | int, ...]
    details: dict[str, object]


def _map_error_code(pydantic_type: str) -> SchemaErrorCode:
    """把 Pydantic 类别映射为稳定错误码，不将第三方格式暴露为契约。"""

    if pydantic_type == "missing":
        return SchemaErrorCode.MISSING_FIELD
    if pydantic_type == "extra_forbidden":
        return SchemaErrorCode.UNKNOWN_FIELD
    if pydantic_type.endswith("_type"):
        return SchemaErrorCode.INVALID_TYPE

    # 范围、长度、字面量和自定义校验失败，都表示字段大类正确，
    # 但具体值不符合 ForgeMind 允许的范围。
    return SchemaErrorCode.INVALID_VALUE


def map_validation_error(error: ValidationError) -> list[SchemaValidationError]:
    """把一次 Pydantic 校验的全部错误转换为 ForgeMind 稳定契约。"""

    issues: list[SchemaValidationError] = []

    # 返回本次校验发现的全部问题，使 Agent 能一次修复，而不是每发现
    # 一个字段就重复一次请求。
    for item in error.errors(include_url=False):
        pydantic_type = item["type"]
        issues.append(
            SchemaValidationError(
                # Agent 只根据稳定 code 分支，不能依赖 Pydantic 的错误措辞。
                code=_map_error_code(pydantic_type),
                message=item["msg"],
                field_path=tuple(item["loc"]),
                details={"pydantic_type": pydantic_type},
            )
        )

    return issues
