"""Runtime 权限检查使用的严格数据契约。"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from forgemind.schema.base import StrictContractModel
from forgemind.schema.edit_file import EditFileArguments
from forgemind.schema.read_file import ReadFileArguments


class PermissionCheckOutcome(StrEnum):
    """权限检查可能产生的三种互斥结论。"""

    ALLOWED = "allowed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DENIED = "denied"


# 元组本身不可变还不够，其中的每个依据编号也必须是非空字符串。
NonEmptyBasisId = Annotated[str, Field(min_length=1)]


class PermissionCheckResult(StrictContractModel):
    """Runtime 针对一个已接受 Action 得出的权限检查结果。"""

    action_id: str = Field(min_length=1)

    # 业务分支只能读取稳定枚举，不能解析可能变化的自然语言 reason。
    outcome: PermissionCheckOutcome
    reason: str = Field(min_length=1)

    # 每个结论都必须能追溯到权限记录或安全策略。使用 tuple 防止
    # 结果创建后再被追加、删除依据，破坏当时的判断证据。
    basis_ids: tuple[NonEmptyBasisId, ...] = Field(min_length=1)


class PendingReadFilePermissionRequest(StrictContractModel):
    """等待用户确认的 read_file 权限请求快照。"""

    # permission_request_id 标识“这次询问”，action_id 标识“待执行行动”；
    # 二者职责不同，用户决定必须同时关联到正确的询问与行动。
    permission_request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)

    # pending 是不可改写的原始等待事实。用户回答会形成新的决定记录，
    # 不能把本对象原地改成 approved/rejected 而覆盖当时询问的内容。
    status: Literal["pending"]
    action_type: Literal["tool_call"]
    tool_name: Literal["read_file"]

    # 保存完整参数快照，防止用户批准局部读取后，执行范围被扩大。
    arguments: ReadFileArguments
    reason: str = Field(min_length=1)
    basis_ids: tuple[NonEmptyBasisId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_expected_version(self) -> Self:
        """权限确认必须绑定用户看到并批准的具体文件版本。"""

        if self.arguments.expected_version is None:
            raise ValueError("待确认读取请求必须提供 expected_version")
        return self


class PendingEditFilePermissionRequest(StrictContractModel):
    """等待用户确认的 edit_file 权限请求快照。"""

    permission_request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    status: Literal["pending"]
    action_type: Literal["tool_call"]
    tool_name: Literal["edit_file"]
    arguments: EditFileArguments
    reason: str = Field(min_length=1)
    basis_ids: tuple[NonEmptyBasisId, ...] = Field(min_length=1)


PendingPermissionRequest = (
    PendingReadFilePermissionRequest | PendingEditFilePermissionRequest
)


class PermissionDecision(StrEnum):
    """用户对一条具体 pending 权限请求作出的决定。"""

    APPROVE = "approve"
    REJECT = "reject"


class PermissionDecisionRecord(StrictContractModel):
    """保留归一化权限决定及用户原始回答的不可变记录。"""

    permission_decision_id: str = Field(min_length=1)
    permission_request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)

    # 程序只根据稳定枚举进入批准或拒绝分支，不能解析原始文本猜测。
    decision: PermissionDecision

    # 权限只能来自真实用户决定，Agent 预测不能伪装成用户授权。
    source: Literal["user"]

    # 原话不能被归一化枚举覆盖。它用于审计用户是否附带了范围、
    # 条件或其他可能影响授权解释的信息。
    raw_response: str = Field(min_length=1)
