from enum import StrEnum
from typing import Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel
from forgemind.schema.read_file import ReadFileResult


class ObservationErrorCode(StrEnum):
    """Runtime/Tool Observation 使用的稳定错误码。"""

    PERMISSION_DENIED = "PERMISSION_DENIED"
    VERSION_MISMATCH = "VERSION_MISMATCH"


class ObservationErrorDetail(StrictContractModel):
    """一项不可变、可序列化的错误补充信息。"""

    key: str = Field(min_length=1)
    value: str


class ObservationError(StrictContractModel):
    """拒绝或失败 Observation 中的结构化错误。"""

    code: ObservationErrorCode
    message: str = Field(min_length=1)

    # 使用 tuple 而不是 list，避免 frozen 模型内部仍能追加或删除详情。
    details: tuple[ObservationErrorDetail, ...] = ()


class RejectedObservation(StrictContractModel):
    """Runtime 在调用 Tool 前拒绝 Action 后形成的事实记录。"""

    action_id: str = Field(min_length=1)
    status: Literal["rejected"]
    error: ObservationError


class FailedObservation(StrictContractModel):
    """Tool 已被调用，但没有产生成功结果时形成的事实记录。"""

    action_id: str = Field(min_length=1)
    status: Literal["failed"]
    error: ObservationError


class ReadFileSuccessObservation(StrictContractModel):
    """read_file 成功执行并取得实际结果后形成的事实记录。"""

    action_id: str = Field(min_length=1)
    status: Literal["success"]
    result: ReadFileResult


TerminalObservation = (
    RejectedObservation | FailedObservation | ReadFileSuccessObservation
)
