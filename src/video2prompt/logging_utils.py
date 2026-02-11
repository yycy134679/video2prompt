"""日志初始化。"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path


class SecretMaskFilter(logging.Filter):
    """简单敏感信息脱敏过滤器。"""

    def __init__(self) -> None:
        super().__init__()
        self._tokens = [
            token
            for token in [
                os.getenv("GEMINI_API_KEY", ""),
                os.getenv("VOLCENGINE_API_KEY", ""),
                os.getenv("ARK_API_KEY", ""),
            ]
            if token
        ]
        self._patterns = [
            re.compile(r"(Authorization\s*:\s*Bearer\s+)([^\s]+)", re.IGNORECASE),
            re.compile(r"(\"Authorization\"\s*:\s*\"Bearer\s+)([^\"]+)(\")", re.IGNORECASE),
            re.compile(r"(GEMINI_API_KEY\s*=\s*)([^\s]+)", re.IGNORECASE),
            re.compile(r"(VOLCENGINE_API_KEY\s*=\s*)([^\s]+)", re.IGNORECASE),
            re.compile(r"(ARK_API_KEY\s*=\s*)([^\s]+)", re.IGNORECASE),
        ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for token in self._tokens:
            msg = msg.replace(token, "***")
        for pattern in self._patterns:
            msg = pattern.sub(r"\1***\3" if pattern.groups == 3 else r"\1***", msg)

        record.msg = msg
        record.args = ()
        return True


def setup_logging(log_file: str, level: str = "INFO") -> logging.Logger:
    """初始化应用日志。"""

    logger = logging.getLogger("video2prompt")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers = []
    logger.propagate = False

    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    mask_filter = SecretMaskFilter()
    file_handler.addFilter(mask_filter)
    stream_handler.addFilter(mask_filter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
