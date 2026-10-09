"""为执行用户项目代码的子进程建立最小、无服务器密钥的环境。"""

from collections.abc import Mapping
import os
from pathlib import Path
import re


# 这些变量只描述操作系统和基础进程查找行为，不包含应用凭据。
SAFE_PARENT_ENVIRONMENT_NAMES = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "TZ",
)


def build_safe_process_environment(
    temporary_root: Path,
    *,
    parent_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """只复制运行所需变量，并把临时目录绑定到本次 Tool 执行。"""

    source = os.environ if parent_environment is None else parent_environment
    environment = {
        name: source[name]
        for name in SAFE_PARENT_ENVIRONMENT_NAMES
        if name in source
    }
    temporary_path = str(temporary_root.resolve())
    environment.update(
        {
            "TEMP": temporary_path,
            "TMP": temporary_path,
            "TMPDIR": temporary_path,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            # Tool 运行产生的字节码属于临时执行数据，不应污染或进入用户工作区 ZIP。
            "PYTHONPYCACHEPREFIX": str((temporary_root / "pycache").resolve()),
        }
    )
    return environment


def redact_process_temporary_path(text: str, temporary_root: Path) -> str:
    """隐藏 Tool 私有临时目录，同时保留其余真实进程输出。"""

    resolved = temporary_root.resolve()
    path_texts = {
        str(temporary_root),
        temporary_root.as_posix(),
        str(resolved),
        resolved.as_posix(),
    }
    redacted = text
    for path_text in sorted(path_texts, key=len, reverse=True):
        redacted = re.sub(
            re.escape(path_text),
            "<forgemind-temp>",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted
