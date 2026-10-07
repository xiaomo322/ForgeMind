from fastapi.testclient import TestClient

from forgemind.web.learning_sse import app, generate_demo_events


client = TestClient(app)


def test_learning_sse_returns_three_complete_events() -> None:
    """客户端应从一个 HTTP 响应中收到三条完整且有序的事件。"""

    # 第一步（执行动作）：打开流式响应，并把收到的文本块保存下来。
    with client.stream("GET", "/learning/sse") as response:
        print("响应对象：", response)
        text_chunks = list(response.iter_text())

    # 第二步（观察结果）：先打印中间值，帮助理解客户端实际收到了什么。
    body = "".join(text_chunks)
    print("文本块数量：", len(text_chunks))
    print("完整响应正文：\n", body)

    # 第三步（检查结果）：用 assert 固定正确行为，错误时测试才会失败。
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

    # 第一步（准备数据）：这里只创建生成器对象，函数体还没有开始运行。
    events = generate_demo_events()

    # 第二步（执行动作）：每次 next() 让生成器继续到下一个 yield。
    first = next(events)
    second = next(events)
    third = next(events)

    # 第三步（观察结果）：打印每一次 next() 分别取得的事件。
    print("第一次 next()：\n", first)
    print("第二次 next()：\n", second)
    print("第三次 next()：\n", third)

    # 第四步（检查结果）：确认生成器没有跳过或颠倒事件。
    assert "任务开始" in first
    assert "正在执行" in second
    assert "任务完成" in third
