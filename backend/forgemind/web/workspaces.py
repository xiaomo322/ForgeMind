"""把浏览器上传的 Python 文件保存为隔离工作区。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from tempfile import mkdtemp
from typing import Sequence
from uuid import uuid4

from pydantic import Field

from forgemind.schema.base import StrictContractModel


MAX_WORKSPACE_FILE_COUNT = 20
MAX_WORKSPACE_FILE_SIZE_BYTES = 1024 * 1024
MAX_WORKSPACE_TOTAL_SIZE_BYTES = 5 * 1024 * 1024
_WORKSPACE_ID_PATTERN = re.compile(
    r"^workspace_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class WorkspaceUploadError(ValueError):
    """所有可安全转换为 HTTP 客户端错误的上传异常基类。"""


class EmptyWorkspaceUploadError(WorkspaceUploadError):
    pass


class TooManyWorkspaceFilesError(WorkspaceUploadError):
    pass


class InvalidWorkspaceFilenameError(WorkspaceUploadError):
    pass


class UnsupportedWorkspaceFileTypeError(WorkspaceUploadError):
    pass


class InvalidWorkspaceEncodingError(WorkspaceUploadError):
    pass


class DuplicateWorkspaceFilenameError(WorkspaceUploadError):
    pass


class WorkspaceFileTooLargeError(WorkspaceUploadError):
    pass


class WorkspaceUploadTooLargeError(WorkspaceUploadError):
    pass


class UnknownWorkspaceError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceUpload:
    """HTTP 层已经读取到内存、等待验证和持久化的单个文件。"""

    filename: str
    content: bytes


class UploadedFileInfo(StrictContractModel):
    """可以返回给浏览器的文件元数据，不包含服务器路径。"""

    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)


class UploadedWorkspace(StrictContractModel):
    """创建完成后可安全公开的工作区信息。"""

    workspace_id: str = Field(min_length=1)
    files: tuple[UploadedFileInfo, ...] = Field(min_length=1)
    file_count: int = Field(ge=1)
    total_size_bytes: int = Field(ge=0)


class FileSystemWorkspaceStore:
    """在一个受控根目录下创建并解析浏览器上传的工作区。"""

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()
        self._storage_root.mkdir(parents=True, exist_ok=True)

    @property
    def storage_root(self) -> Path:
        """供应用装配和测试检查持久化位置。"""

        return self._storage_root

    def create(self, uploads: Sequence[WorkspaceUpload]) -> UploadedWorkspace:
        """先完整校验，再写临时目录，最后原子发布为正式工作区。"""

        validated = self._validate_uploads(uploads)
        workspace_id = f"workspace_{uuid4()}"
        final_root = self._storage_root / workspace_id
        temporary_root = Path(mkdtemp(prefix=".upload-", dir=self._storage_root))

        try:
            for upload in validated:
                (temporary_root / upload.filename).write_bytes(upload.content)

            # 同一个磁盘分区内 rename 是原子切换。浏览器只会看到完整目录，
            # 不会在上传到一半时拿到一个可以创建任务的 workspace_id。
            temporary_root.replace(final_root)
        except Exception:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)
            raise

        files = tuple(
            UploadedFileInfo(path=upload.filename, size_bytes=len(upload.content))
            for upload in validated
        )
        return UploadedWorkspace(
            workspace_id=workspace_id,
            files=files,
            file_count=len(files),
            total_size_bytes=sum(file.size_bytes for file in files),
        )

    def resolve(self, workspace_id: str) -> Path:
        """把公开 ID 还原为内部目录，并拒绝路径穿越和未知目录。"""

        if not _WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise UnknownWorkspaceError(workspace_id)

        candidate = (self._storage_root / workspace_id).resolve()
        if candidate.parent != self._storage_root or not candidate.is_dir():
            raise UnknownWorkspaceError(workspace_id)
        return candidate

    def _validate_uploads(
        self,
        uploads: Sequence[WorkspaceUpload],
    ) -> tuple[WorkspaceUpload, ...]:
        """集中验证所有文件，确保失败时磁盘上不留下半成品。"""

        if not uploads:
            raise EmptyWorkspaceUploadError("at least one Python file is required")
        if len(uploads) > MAX_WORKSPACE_FILE_COUNT:
            raise TooManyWorkspaceFilesError(
                f"at most {MAX_WORKSPACE_FILE_COUNT} files are allowed"
            )

        seen_names: set[str] = set()
        total_size = 0
        validated: list[WorkspaceUpload] = []
        for upload in uploads:
            self._validate_filename(upload.filename)

            normalized_name = upload.filename.casefold()
            if normalized_name in seen_names:
                raise DuplicateWorkspaceFilenameError(
                    f"duplicate filename: {upload.filename}"
                )
            seen_names.add(normalized_name)

            file_size = len(upload.content)
            if file_size > MAX_WORKSPACE_FILE_SIZE_BYTES:
                raise WorkspaceFileTooLargeError(
                    f"file exceeds {MAX_WORKSPACE_FILE_SIZE_BYTES} bytes"
                )
            total_size += file_size
            if total_size > MAX_WORKSPACE_TOTAL_SIZE_BYTES:
                raise WorkspaceUploadTooLargeError(
                    f"upload exceeds {MAX_WORKSPACE_TOTAL_SIZE_BYTES} bytes"
                )

            try:
                upload.content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise InvalidWorkspaceEncodingError(
                    f"{upload.filename} must be UTF-8"
                ) from error
            validated.append(upload)

        return tuple(validated)

    @staticmethod
    def _validate_filename(filename: str) -> None:
        """第一版只接受平铺文件名，避免上传内容决定服务器路径。"""

        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or Path(filename).is_absolute()
        ):
            raise InvalidWorkspaceFilenameError("filename must be a flat relative name")
        if Path(filename).suffix.lower() != ".py":
            raise UnsupportedWorkspaceFileTypeError("only .py files are supported")
