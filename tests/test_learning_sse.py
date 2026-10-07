from fastapi.testclient import TestClient

from forgemind.web.learning_sse import app, generate_demo_events


client = TestClient(app)


def test_learning_sse_returns_three_complete_events() -> None:
    """客户端应从一个 HTTP 响应中收到三条完整且有序的事件。"""

    with client.stream("GET", "/learning/sse") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert body == (
        "event: lesson\n"
        'data: {"step":1,"message":"任务开始"}\n\n'
        "event: lesson\n"
        'data: {"step":2,"message":"正在执行"}\n\n'
        "event: lesson\n"
        'data: {"step":3,"message":"任务完成"}\n\n'
    )


def test_generator_pauses_and_keeps_its_position() -> None:
    """每次 next() 只取得下一条事件，生成器保留上次暂停位置。"""

    events = generate_demo_events()

    first = next(events)
    second = next(events)

    assert "任务开始" in first
    assert "正在执行" in second
