from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()


# 第一步：定义 CreateTaskRequest。
# original_request 必须是至少包含一个字符的字符串。
class CreateTaskRequest(BaseModel):
    original_request: str = Field(min_length = 1)

# 第二步：定义 TaskResponse。
# 包含 task_id 和 status 两个字符串字段。
class TaskResponse(BaseModel):
    task_id :str
    status: str

# 第三步：声明 POST /tasks 路由。
# 响应模型使用 TaskResponse，成功状态码使用 201。
@app.post("/tasks",response_model = TaskResponse,status_code = 201)
def create_task(request: CreateTaskRequest) ->TaskResponse:
    return TaskResponse(
        task_id = "task-001",
        status="running"
    )


# 第四步：返回 task_id="task-001"、status="running"。