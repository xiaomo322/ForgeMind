"""ForgeMind 对外流式事件及其 SSE 编码规则。"""

import json

from pydantic import Field, JsonValue

from forgemind.schema.base import StrictContractModel


class StreamEvent(StrictContractModel):
    """一条已经校验、可以安全编码的公开流式事件。"""

    # 事件名只允许协议安全字符，避免换行进入 event: 字段。
    event: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    # sequence 同时用作 SSE id；从 1 开始便于判断事件先后顺序。
    sequence: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    # JsonValue 把载荷限制为真正可以序列化成 JSON 的数据。
    data: dict[str, JsonValue]


def encode_sse_event(event: StreamEvent) -> str:
    """把一条公开事件编码成完整 SSE 消息。"""

    # 协议字段 event 和 id 放在 SSE 行中；任务信息放入 JSON 数据行。
    payload = {
        "task_id": event.task_id,
        "data": event.data,
    }
    data_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    # SSE 使用空行分隔事件，所以结尾必须保留两个换行符。
    return f"event: {event.event}\nid: {event.sequence}\ndata: {data_json}\n\n"
