"""日志初始化。"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from .models import Task


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


class ModelContextFilter(logging.Filter):
    """补齐模型观测字段，避免 formatter 取值报错。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        if not hasattr(record, "api_mode"):
            record.api_mode = "-"
        if not hasattr(record, "prompt_tokens"):
            record.prompt_tokens = 0
        if not hasattr(record, "completion_tokens"):
            record.completion_tokens = 0
        if not hasattr(record, "reasoning_tokens"):
            record.reasoning_tokens = 0
        if not hasattr(record, "cached_tokens"):
            record.cached_tokens = 0
        return True


def build_model_log_extra(task: Task) -> dict[str, Any]:
    """构造统一日志扩展字段。"""
    return {
        "request_id": task.model_request_id or "-",
        "api_mode": task.model_api_mode or "-",
        "prompt_tokens": int(task.model_prompt_tokens or 0),
        "completion_tokens": int(task.model_completion_tokens or 0),
        "reasoning_tokens": int(task.model_reasoning_tokens or 0),
        "cached_tokens": int(task.model_cached_tokens or 0),
    }


def setup_logging(log_file: str, level: str = "INFO", retention_days: int = 7) -> logging.Logger:
    """初始化应用日志。"""

    logger = logging.getLogger("video2prompt")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in logger.handlers:
        handler.close()
    logger.handlers = []
    logger.propagate = False

    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s "
        "| request_id=%(request_id)s api_mode=%(api_mode)s "
        "prompt=%(prompt_tokens)s completion=%(completion_tokens)s "
        "reasoning=%(reasoning_tokens)s cached=%(cached_tokens)s"
    )

    # TimedRotatingFileHandler 的 backupCount 仅统计历史文件，不含当天活跃文件。
    # retention_days=7 表示“当天 + 最近 6 天历史文件”。
    backup_count = max(int(retention_days) - 1, 0)
    file_handler = TimedRotatingFileHandler(
        filename=path,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    mask_filter = SecretMaskFilter()
    model_context_filter = ModelContextFilter()
    file_handler.addFilter(mask_filter)
    stream_handler.addFilter(mask_filter)
    file_handler.addFilter(model_context_filter)
    stream_handler.addFilter(model_context_filter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
