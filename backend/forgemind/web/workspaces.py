"""把浏览器上传的 Python 文件保存为隔离工作区。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
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


class AttachmentPublishIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceUpload:
    """HTTP 层已经读取到内存、等待验证和持久化的单个文件。"""

    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class StagedWorkspaceFile:
    """已经可靠保存、但尚未进入活动 Workspace 的附件。"""

    upload_id: str
    task_id: str
    path: str
    size_bytes: int
    sha256: str
    # 这是服务端内部定位暂存字节的令牌，后续公开模型不能返回它。
    staging_token: str


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

    def stage(
        self,
        *,
        task_id: str,
        project_root: Path,
        uploads: Sequence[WorkspaceUpload],
        next_upload_id: Callable[[], str],
    ) -> tuple[StagedWorkspaceFile, ...]:
        """保存附件，但在 Runtime 到达安全边界前不修改活动项目。"""

        if not task_id.strip():
            raise ValueError("task_id 不能只包含空白字符")

        # project_root 必须是本 Store 创建并管理的 Workspace。这个检查防止
        # 调用者把暂存附件错误地绑定到任意服务器目录。
        resolved_project_root = project_root.resolve()
        if (
            resolved_project_root.parent != self._storage_root
            or not resolved_project_root.is_dir()
        ):
            raise UnknownWorkspaceError(str(project_root))

        validated = self._validate_uploads(uploads)
        active_names = {
            path.name.casefold()
            for path in resolved_project_root.iterdir()
            if path.is_file()
        }
        staging_prefix = f".staged-{resolved_project_root.name}-"
        staged_names = {
            path.name.casefold()
            for directory in self._storage_root.glob(f"{staging_prefix}*")
            if directory.is_dir()
            for path in directory.iterdir()
            if path.is_file()
        }
        if len(active_names | staged_names) + len(validated) > MAX_WORKSPACE_FILE_COUNT:
            raise TooManyWorkspaceFilesError(
                f"at most {MAX_WORKSPACE_FILE_COUNT} files are allowed"
            )
        for upload in validated:
            if upload.filename.casefold() in active_names | staged_names:
                raise DuplicateWorkspaceFilenameError(
                    f"duplicate filename: {upload.filename}"
                )
        temporary_root = Path(mkdtemp(prefix=staging_prefix, dir=self._storage_root))
        staged_files: list[StagedWorkspaceFile] = []

        try:
            for upload in validated:
                upload_id = next_upload_id()
                staged_path = temporary_root / upload.filename
                staged_path.write_bytes(upload.content)
                staged_files.append(
                    StagedWorkspaceFile(
                        upload_id=upload_id,
                        task_id=task_id,
                        path=upload.filename,
                        size_bytes=len(upload.content),
                        sha256=sha256(upload.content).hexdigest(),
                        staging_token=f"{temporary_root.name}/{upload.filename}",
                    )
                )
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

        return tuple(staged_files)

    def publish(
        self,
        project_root: Path,
        staged: StagedWorkspaceFile,
    ) -> None:
        """把一条权威暂存记录原子移动到活动 Workspace。"""

        resolved_project_root = project_root.resolve()
        if (
            resolved_project_root.parent != self._storage_root
            or not resolved_project_root.is_dir()
        ):
            raise UnknownWorkspaceError(str(project_root))
        source = (self._storage_root / staged.staging_token).resolve()
        if self._storage_root not in source.parents or not source.is_file():
            raise AttachmentPublishIntegrityError("暂存附件不存在或路径无效")
        if sha256(source.read_bytes()).hexdigest() != staged.sha256:
            raise AttachmentPublishIntegrityError("暂存附件哈希不匹配")
        destination = (resolved_project_root / staged.path).resolve()
        if destination.parent != resolved_project_root:
            raise AttachmentPublishIntegrityError("附件目标路径越界")
        if destination.exists():
            raise DuplicateWorkspaceFilenameError(
                f"duplicate filename: {staged.path}"
            )
        source.replace(destination)
        try:
            source.parent.rmdir()
        except OSError:
            pass

    def reconcile_publish(
        self,
        project_root: Path,
        staged: StagedWorkspaceFile,
    ) -> str:
        """根据源、目标和哈希判断中断后的真实发布状态。"""

        resolved_project_root = project_root.resolve()
        source = (self._storage_root / staged.staging_token).resolve()
        destination = (resolved_project_root / staged.path).resolve()
        source_exists = source.is_file()
        destination_exists = destination.is_file()
        if source_exists and not destination_exists:
            if sha256(source.read_bytes()).hexdigest() == staged.sha256:
                return "staged"
        elif destination_exists and not source_exists:
            if sha256(destination.read_bytes()).hexdigest() == staged.sha256:
                return "published"
        raise AttachmentPublishIntegrityError("无法根据哈希确认附件发布状态")

    def delete_staged(self, staged: StagedWorkspaceFile) -> None:
        """删除尚未发布的暂存字节；已发布文件不能通过此入口删除。"""
        source = (self._storage_root / staged.staging_token).resolve()
        if self._storage_root not in source.parents or not source.is_file():
            raise AttachmentPublishIntegrityError("暂存附件不存在或路径无效")
        source.unlink()
        try:
            source.parent.rmdir()
        except OSError:
            pass

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
