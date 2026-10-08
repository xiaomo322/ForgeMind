"""用户后续消息与附件的追加式事实。"""

from pydantic import Field, model_validator
from typing import Self

from forgemind.schema.base import StrictContractModel


class StagedAttachmentRecord(StrictContractModel):
    upload_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    staging_token: str = Field(min_length=1)


class TaskMessageRecord(StrictContractModel):
    message_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    content: str | None = None
    attachment_upload_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_content_or_attachment(self) -> Self:
        if (self.content is None or not self.content.strip()) and not self.attachment_upload_ids:
            raise ValueError("消息必须包含文字或附件")
        if len(set(self.attachment_upload_ids)) != len(self.attachment_upload_ids):
            raise ValueError("附件编号不能重复")
        return self


class TaskMessageApplicationRecord(StrictContractModel):
    message_application_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    applied_after_action_sequence: int = Field(ge=0)


class TaskMessageStateView(StrictContractModel):
    message: TaskMessageRecord
    application: TaskMessageApplicationRecord | None
    attachments: tuple[StagedAttachmentRecord, ...] = ()

