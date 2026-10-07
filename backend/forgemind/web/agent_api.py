"""把 ForgeMindApplication 暴露为 FastAPI SSE 与用户回答接口。"""

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
from forgemind.web.public_models import PublicTaskState, build_public_task_state
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
    UnknownWorkspaceError,
)


class CreateTaskRequest(StrictContractModel):
    """前端创建任务时提交的用户目标和公开工作区编号。"""

    original_request: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)

    @field_validator("original_request", "workspace_id")
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
    workspace_id: str = Field(min_length=1)
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


class PermissionDecisionRequest(StrictContractModel):
    """浏览器对一条特定权限请求作出的明确决定。"""

    decision: Literal["approve", "reject"]
    raw_response: str = Field(min_length=1)

    @field_validator("raw_response")
    @classmethod
    def require_visible_response(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_response 不能只包含空白字符")
        return value


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

        if workspace_store is None:
            raise HTTPException(status_code=503, detail="workspace store is unavailable")
        try:
            # 浏览器只能提交不可解释为路径的公开 ID。真实绝对路径由服务器
            # 在受控根目录中解析，不能由 HTTP 客户端自行指定。
            project_root = workspace_store.resolve(request.workspace_id)
        except UnknownWorkspaceError as error:
            raise HTTPException(status_code=404, detail="workspace not found") from error

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
            workspace_id=request.workspace_id,
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

    @app.get("/tasks/{task_id}", response_model=PublicTaskState)
    def get_task_state(task_id: str) -> PublicTaskState:
        """返回页面刷新后可以重建时间线的权威任务视图。"""

        try:
            view = application.get_task(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error
        return build_public_task_state(view)

    @app.post(
        "/tasks/{task_id}/permissions/{permission_request_id}",
        response_model=PublicTaskState,
    )
    def decide_task_permission(
        task_id: str,
        permission_request_id: str,
        request: PermissionDecisionRequest,
    ) -> PublicTaskState:
        """记录批准或拒绝，再返回数据库中的最新公开状态。"""

        try:
            application.decide_permission(
                task_id=task_id,
                permission_request_id=permission_request_id,
                approve=request.decision == "approve",
                raw_response=request.raw_response,
            )
            return build_public_task_state(application.get_task(task_id))
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="task or permission request not found",
            ) from error
        except (ValueError, RuntimeError) as error:
            # 任务不再等待这条请求、请求不属于当前 Action 等状态冲突
            # 都不能被客户端重试成一次新的授权。
            raise HTTPException(status_code=409, detail=str(error)) from error

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
