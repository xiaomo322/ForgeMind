"""用于理解 FastAPI 与 SSE 数据流的最小示例。"""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse


app = FastAPI()


def generate_demo_events() -> Iterator[str]:
    """逐次产出三条完整 SSE 事件。"""

    # 每次 yield 后函数暂停；StreamingResponse 取得这一块并继续发送。
    # 末尾两个换行表示一条 SSE 事件已经完整结束。
    yield 'event: lesson\ndata: {"step":1,"message":"任务开始"}\n\n'
    yield 'event: lesson\ndata: {"step":2,"message":"正在执行"}\n\n'
    yield 'event: lesson\ndata: {"step":3,"message":"任务完成"}\n\n'


@app.get("/learning/sse")
def stream_lesson() -> StreamingResponse:
    """把生成器产生的每一块内容写入同一个 HTTP 响应。"""

    return StreamingResponse(
        generate_demo_events(),
        media_type="text/event-stream",
    )
