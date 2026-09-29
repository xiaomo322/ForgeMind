"""把严格 AgentTaskContext 渲染成稳定 JSON 载荷。"""

import json

from forgemind.schema.context import AgentContextEnvelope, AgentTaskContext


def render_agent_task_context(context: AgentTaskContext) -> str:
    """保留中文并以稳定键顺序渲染带版本的 Context Envelope。"""

    # 第一步：构造 AgentContextEnvelope(context=context)，保存为 envelope。
    # schema_version 和 context_type 使用模型中固定的默认字面量。
    envelope = AgentContextEnvelope(context=context)
    # 第二步：调用 envelope.model_dump(mode="json")，把 Pydantic 模型、
    # 枚举和元组转换为 JSON 可以表示的 Python 数据。
    payload = envelope.model_dump(mode="json")
    # 第三步：调用 json.dumps：ensure_ascii=False 保留中文；
    # sort_keys=True 固定键顺序；indent=2 生成便于检查的缩进文本。
    # 第四步：返回 json.dumps 的字符串结果。
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
