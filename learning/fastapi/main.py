from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


class CreateTaskRequest(BaseModel):
    original_request: str = Field(min_length=1)
    project_root:str = Field(min_length=1)


class TaskResponse(BaseModel):
    task_id: str
    status: str
    original_request:str

task_state: dict[str,TaskResponse] = {}

class TaskNotFoundError(ValueError):
    def __init__(self,task_id:str)->None:
        self.task_id = task_id
        super().__init__(f"任务不存在：{task_id}")

def create_task_service(
        request:CreateTaskRequest,
)->TaskResponse:
    task =TaskResponse(
        task_id=f"task_{uuid4()}",
        status="running",
        original_request=request.original_request,
    )
    task_state[task.task_id] =task
    return task

def get_task_service(task_id: str) -> TaskResponse:
    if task_id not in task_state:
        raise TaskNotFoundError(task_id)

    return task_state[task_id]
@app.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(request: CreateTaskRequest) -> TaskResponse:
    return  create_task_service(request)

@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    try:
        return get_task_service(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
