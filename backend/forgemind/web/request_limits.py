"""Web 请求在进入 multipart 解析前使用的资源上限。"""

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from forgemind.web.workspaces import (
    MAX_WORKSPACE_ARCHIVE_SIZE_BYTES,
    MAX_WORKSPACE_TOTAL_SIZE_BYTES,
)


# 为 multipart boundary、Content-Disposition 和最多 20 个文件名预留空间。
MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = max(
    MAX_WORKSPACE_TOTAL_SIZE_BYTES,
    MAX_WORKSPACE_ARCHIVE_SIZE_BYTES,
) + 256 * 1024


class _RequestBodyTooLarge(Exception):
    pass


class WorkspaceUploadBodyLimitMiddleware:
    """限制上传请求原始字节数，避免框架先把超大 body 写入临时磁盘。"""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in {
            "/workspaces",
            "/workspaces/archive",
        }:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > MAX_WORKSPACE_UPLOAD_REQUEST_BYTES:
                await self._reject(scope, receive, send)
                return

        received_size = 0

        async def limited_receive() -> Message:
            nonlocal received_size
            message = await receive()
            if message["type"] == "http.request":
                received_size += len(message.get("body", b""))
                if received_size > MAX_WORKSPACE_UPLOAD_REQUEST_BYTES:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": "workspace upload request is too large"},
            status_code=413,
        )
        await response(scope, receive, send)
