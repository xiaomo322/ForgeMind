"""把 ForgeMindApplication 暴露为 FastAPI SSE 与用户回答接口。"""

from pathlib import Path
from typing import Annotated
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from forgemind.application import ForgeMindApplication
from forgemind.runtime.user_responses import (
    InvalidUserResponseSelectionError,
    UserResponseQuestionMismatchError,
)
from forgemind.schema.base import StrictContractModel
from forgemind.state.sqlite_state import (
    UserAnswerQuestionNotCurrentError,
    UserAnswerRequiresWaitingStatusError,
)
from forgemind.state.user_response_registry import (
    QuestionActionTypeError,
    UnknownQuestionActionIdError,
)
from forgemind.web.agent_events import generate_agent_step_events
from forgemind.web.events import encode_sse_event
from forgemind.web.workspaces import (
    DuplicateWorkspaceFilenameError,
    FileSystemWorkspaceStore,
    MAX_WORKSPACE_FILE_SIZE_BYTES,
    TooManyWorkspaceFilesError,
    UnsupportedWorkspaceFileTypeError,
    UploadedWorkspace,
    WorkspaceFileTooLargeError,
    WorkspaceUpload,
    WorkspaceUploadError,
    WorkspaceUploadTooLargeError,
)


class CreateTaskRequest(StrictContractModel):
    """前端创建任务时提交的用户目标和本地项目目录。"""

    original_request: str = Field(min_length=1)
    project_root: str = Field(min_length=1)

    @field_validator("original_request", "project_root")
    @classmethod
    def require_visible_text(cls, value: str) -> str:
        """拒绝只有空格或换行的文本，同时保留用户输入原文。"""

        if not value.strip():
            raise ValueError("必填文本不能只包含空白字符")
        return value


class CreatedTaskResponse(StrictContractModel):
    """任务及初始状态已经写入 State 后的公开结果。"""

    task_id: str = Field(min_length=1)
    original_request: str = Field(min_length=1)
    project_root: str = Field(min_length=1)
    status: Literal["running"]
    revision: int = Field(ge=1)


class AnswerQuestionRequest(StrictContractModel):
    """浏览器提交回答时必须提供的字段。"""

    # 问题 ID 来自 task.waiting_user 事件，回答必须明确对应到那个问题。
    question_action_id: str = Field(min_length=1)
    # 保留用户原话；Runtime 会把它写入不可变 UserResponseRecord。
    raw_response: str = Field(min_length=1)
    # 单选题传具体选项，自由文本题不传或传 null。
    selected_option: str | None = Field(default=None, min_length=1)


class AnswerQuestionAccepted(StrictContractModel):
    """回答成功写入 State 后返回给客户端的确认信息。"""

    response_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    question_action_id: str = Field(min_length=1)
    status: Literal["running"]
    revision: int = Field(ge=1)


def create_agent_stream_app(
    application: ForgeMindApplication,
    workspace_store: FileSystemWorkspaceStore | None = None,
) -> FastAPI:
    """使用调用方提供的 Application 创建可测试的 Web 应用。"""

    app = FastAPI()

    @app.post(
        "/workspaces",
        response_model=UploadedWorkspace,
        status_code=http_status.HTTP_201_CREATED,
    )
    async def upload_workspace(
        files: Annotated[list[UploadFile], File(min_length=1)],
    ) -> UploadedWorkspace:
        """接收浏览器文件，并交给受控存储层创建隔离工作区。"""

        if workspace_store is None:
            raise HTTPException(status_code=503, detail="workspace uploads are unavailable")

        uploads: list[WorkspaceUpload] = []
        try:
            for file in files:
                # 多读取 1 字节即可判断是否越界，又不会把任意大文件完整放入内存。
                content = await file.read(MAX_WORKSPACE_FILE_SIZE_BYTES + 1)
                uploads.append(WorkspaceUpload(file.filename or "", content))
        finally:
            for file in files:
                await file.close()

        try:
            return workspace_store.create(uploads)
        except UnsupportedWorkspaceFileTypeError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except DuplicateWorkspaceFilenameError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (
            WorkspaceFileTooLargeError,
            WorkspaceUploadTooLargeError,
            TooManyWorkspaceFilesError,
        ) as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except WorkspaceUploadError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/tasks",
        response_model=CreatedTaskResponse,
        status_code=http_status.HTTP_201_CREATED,
    )
    def create_task(request: CreateTaskRequest) -> CreatedTaskResponse:
        """创建持久化任务，返回前端后续操作所需的 task_id。"""

        project_root = Path(request.project_root)
        if not project_root.is_absolute() or not project_root.is_dir():
            # 项目目录属于 HTTP 输入语义，必须在产生 task_id 和写入 State
            # 之前拒绝，避免保存一个后续所有 Tool 都无法使用的任务。
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="project_root must be an existing absolute directory",
            )

        # Application 负责生成权威 ID，并把任务和 revision=1 的
        # RUNNING 状态原子写入 SQLite；创建任务本身不会调用模型。
        task = application.create_task(
            request.original_request,
            project_root,
        )
        task_view = application.get_task(task.task_id)

        # 返回值取自刚写入后重新读取的权威视图，避免 Web 层自己猜状态。
        return CreatedTaskResponse(
            task_id=task_view.task.task_id,
            original_request=task_view.task.original_request,
            project_root=task_view.task.project_root,
            status=task_view.current_status.status.value,
            revision=task_view.current_status.revision,
        )

    @app.get("/tasks/{task_id}/events")
    def stream_task_events(
        task_id: str,
        max_steps: Annotated[int, Query(ge=1, le=20)] = 20,
    ) -> StreamingResponse:
        """逐轮运行指定任务，并返回 SSE 事件流。"""

        # 生成器表达式保持惰性：StreamingResponse 请求下一块数据时，
        # generate_agent_step_events 才驱动下一轮 Agent。
        encoded_events = (
            encode_sse_event(event)
            for event in generate_agent_step_events(
                application,
                task_id,
                max_steps=max_steps,
            )
        )
        return StreamingResponse(
            encoded_events,
            media_type="text/event-stream",
        )

    @app.post(
        "/tasks/{task_id}/answers",
        response_model=AnswerQuestionAccepted,
    )
    def answer_task_question(
        task_id: str,
        request: AnswerQuestionRequest,
    ) -> AnswerQuestionAccepted:
        """保存用户回答并将任务恢复为 RUNNING，等待客户端重连事件流。"""

        try:
            # Web 层只负责接收并校验 HTTP 数据；实际问题编号校验和
            # 原子 State 写入由 Application/Runtime/SQLite 完成。
            result = application.answer_question(
                task_id=task_id,
                question_action_id=request.question_action_id,
                raw_response=request.raw_response,
                selected_option=request.selected_option,
            )
        except KeyError as error:
            # State 中不存在任务，客户端无法继续为这个任务提交回答。
            raise HTTPException(status_code=404, detail="task not found") from error
        except UnknownQuestionActionIdError as error:
            raise HTTPException(
                status_code=404,
                detail="question_action_id not found",
            ) from error
        except QuestionActionTypeError as error:
            raise HTTPException(
                status_code=409,
                detail="question_action_id does not refer to a user question",
            ) from error
        except InvalidUserResponseSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (
            UserResponseQuestionMismatchError,
            UserAnswerQuestionNotCurrentError,
            UserAnswerRequiresWaitingStatusError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        # 只在 Application 明确返回“持久化成功”后应答；本接口不在 POST
        # 请求里运行模型，客户端需要再 GET events 才会恢复 Agent。
        return AnswerQuestionAccepted(
            response_id=result.response.response_id,
            task_id=result.response.task_id,
            question_action_id=result.response.question_action_id,
            status=result.running_status.status.value,
            revision=result.running_status.revision,
        )

    return app
