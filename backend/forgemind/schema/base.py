from pydantic import BaseModel, ConfigDict


class StrictContractModel(BaseModel):
    """所有跨越 ForgeMind 信任边界的数据模型基类。"""

    model_config = ConfigDict(
        # 未知字段可能表达了 Agent 的真实意图。静默丢弃会让实际执行
        # 与 Agent 请求不一致，因此必须明确拒绝。
        extra="forbid",
        # 禁止把字符串 "1" 等输入自动转换为整数 1；Agent 必须直接
        # 产生符合契约的数据，Runtime 不替它猜测类型。
        strict=True,
        # 校验完成后禁止原地修改。任何内容变化都必须重新构造模型，
        # 让新数据重新经过完整校验并形成新的权威记录。
        frozen=True,
    )
