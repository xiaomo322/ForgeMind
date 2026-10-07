"""用可观察测试学习 ForgeMind 的统一 SSE 事件契约。"""

import pytest
from pydantic import ValidationError

from forgemind.web.events import StreamEvent, encode_sse_event


def test_encode_stream_event_preserves_contract_and_chinese() -> None:
    """编码器应把事件对象转换成一条完整的 SSE 消息。"""

    # 第一步（准备数据）：先创建结构明确的事件对象，不手写协议字符串。
    event = StreamEvent(
        event="lesson",
        sequence=1,
        task_id="task-learning",
        data={"step": 1, "message": "任务开始"},
    )

    # 第二步（执行动作）：由一个专门函数统一编码 SSE 格式。
    encoded = encode_sse_event(event)

    # 第三步（观察结果）：打印真实文本；repr() 可以看清 \n 和结尾空行。
    print("事件对象：", event)
    print("SSE 编码结果：", repr(encoded))

    # 第四步（检查结果）：顺序、紧凑 JSON、中文和末尾空行都必须准确。
    assert encoded == (
        "event: lesson\n"
        "id: 1\n"
        'data: {"task_id":"task-learning","data":{"step":1,"message":"任务开始"}}\n\n'
    )


def test_stream_event_rejects_invalid_fields_without_guessing() -> None:
    """错误字段应一次性形成清楚的校验列表。"""

    # 第一步（准备数据）：同时制造协议注入、错误类型和空 task_id。
    invalid_values = {
        "event": "lesson\ndata: forged",
        "sequence": "1",
        "task_id": "",
        "data": {},
    }

    # 第二步（执行动作）：pytest.raises 保存预期出现的 ValidationError。
    with pytest.raises(ValidationError) as captured:
        StreamEvent.model_validate(invalid_values)

    # 第三步（观察结果）：errors() 返回每个错误的位置、类型和原输入。
    errors = captured.value.errors()
    print("StreamEvent 校验错误列表：", errors)

    # 第四步（检查结果）：三个问题都被报告，模型没有擅自修正任何字段。
    error_types_by_field = {error["loc"][0]: error["type"] for error in errors}
    assert error_types_by_field == {
        "event": "string_pattern_mismatch",
        "sequence": "int_type",
        "task_id": "string_too_short",
    }
