"""从单一 TOML 文件读取可切换的模型厂商配置。"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field

from forgemind.schema.base import StrictContractModel


class ModelProviderConfig(StrictContractModel):
    """创建一个模型适配器所需的非敏感配置。"""

    adapter: Literal["openai_compatible"]
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key_env: str = Field(
        min_length=1,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    timeout_seconds: int = Field(gt=0)


class ModelConfigDocument(StrictContractModel):
    """对应 model.toml 的最外层结构。"""

    model: ModelProviderConfig


def load_model_provider_config(path: Path) -> ModelProviderConfig:
    """读取 TOML，并且只返回通过严格校验的模型配置。"""

    # 第一步：使用 path.open("rb") 以二进制只读方式打开配置文件。
    # 第二步：把文件对象交给 tomllib.load(...)，保存返回的字典。
    with path.open("rb") as config_file:
        raw_config = tomllib.load(config_file)
    # 第三步：调用 ModelConfigDocument.model_validate(...) 校验字典。
    document = ModelConfigDocument.model_validate(raw_config)
    # 第四步：返回校验结果的 .model 字段。
    return document.model
