"""把内部值编码为不会泄露服务器工作目录的公开 JSON 数据。"""

from collections.abc import Iterable
from pathlib import Path
import re
from typing import Any

from fastapi.encoders import jsonable_encoder


def encode_public_value(
    value: object,
    *,
    hidden_paths: Iterable[str | Path] = (),
) -> Any:
    """JSON 化内部值，并递归替换指定服务器绝对路径。"""

    encoded = jsonable_encoder(value)
    path_texts: set[str] = set()
    for path in hidden_paths:
        resolved = Path(path).resolve()
        path_texts.add(str(resolved))
        path_texts.add(resolved.as_posix())

    # 先替换较长路径，避免一个父目录提前替换后留下子路径片段。
    ordered_paths = tuple(sorted(filter(None, path_texts), key=len, reverse=True))

    def redact(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: redact(child) for key, child in item.items()}
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, str):
            redacted = item
            for path_text in ordered_paths:
                redacted = re.sub(
                    re.escape(path_text),
                    "<workspace>",
                    redacted,
                    flags=re.IGNORECASE,
                )
            return redacted
        return item

    return redact(encoded)
