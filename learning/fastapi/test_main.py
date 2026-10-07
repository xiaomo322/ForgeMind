from fastapi.testclient import TestClient

from .main import (
    CreateTaskRequest,
    app,
    create_task_service,
    task_state,
)


client = TestClient(app)


def test_create_task_returns_and_saves_task() -> None:
    task_state.clear()

    response = client.post(
        "/tasks",
        json={
            "original_request": "第一次修复折扣计算错误",
            "project_root": "F:/projects/shop",
        },
    )

    assert response.status_code == 201

    created_task = response.json()
    task_id = created_task["task_id"]

    assert task_id
    assert created_task["status"] == "running"
    assert created_task["original_request"] == "第一次修复折扣计算错误"

    saved_task = task_state[task_id]
    assert saved_task.model_dump() == created_task


def test_invalid_request_does_not_save_task() -> None:
    task_state.clear()

    response = client.post(
        "/tasks",
        json={
            "original_request": "",
            "project_root": "F:/projects/shop",
        },
    )

    assert response.status_code == 422
    assert task_state == {}


def test_service_saves_task_before_returning() -> None:
    task_state.clear()

    task = create_task_service(
        CreateTaskRequest(
            original_request="修复折扣计算错误",
            project_root="F:/projects/shop",
        )
    )

    assert task_state[task.task_id] == task


def test_get_task_returns_saved_task() -> None:
    task_state.clear()

    create_response = client.post(
        "/tasks",
        json={
            "original_request": "修复折扣计算错误",
            "project_root": "F:/projects/shop",
        },
    )

    assert create_response.status_code == 201

    created_task = create_response.json()
    task_id = created_task["task_id"]

    response = client.get(f"/tasks/{task_id}")
    print("--"*50)
    print(task_id)
    assert response.status_code == 200
    assert response.json() == created_task

def test_get_missing_task_returns_404() -> None:
    task_state.clear()

    response = client.get("/tasks/not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "任务不存在：not-exist",
    }


def test_update_task_status_saves_and_returns_updated_task() -> None:
    task_state.clear()

    create_response = client.post(
        "/tasks",
        json={
            "original_request": "修复折扣计算错误",
            "project_root": "F:/projects/shop",
        },
    )
    created_task = create_response.json()
    task_id = created_task["task_id"]

    response = client.patch(
        f"/tasks/{task_id}",
        json={"status": "completed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert task_state[task_id].status == "completed"
