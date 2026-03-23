from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytest

from video2prompt.logging_utils import setup_logging


def _close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_setup_logging_use_daily_rotation_and_retention(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "app.log"

    logger = setup_logging(str(log_path), "INFO", retention_days=7)
    try:
        file_handlers = [h for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)]
        assert len(file_handlers) == 1

        file_handler = file_handlers[0]
        assert Path(file_handler.baseFilename) == log_path
        assert file_handler.when == "MIDNIGHT"
        assert file_handler.suffix == "%Y-%m-%d"
        assert file_handler.backupCount == 6

        logger.info("日志写入测试")
        assert log_path.exists()
    finally:
        _close_logger(logger)


def test_setup_logging_keep_current_day_only_when_retention_is_one(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "app.log"

    logger = setup_logging(str(log_path), "INFO", retention_days=1)
    try:
        file_handlers = [h for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].backupCount == 0
    finally:
        _close_logger(logger)


def test_setup_logging_uses_runtime_log_path_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEO2PROMPT_APP_SUPPORT_DIR", str(tmp_path / "support"))
    log_path = tmp_path / "support" / "logs" / "app.log"

    logger = setup_logging(str(log_path), "INFO", retention_days=3)
    try:
        logger.info("runtime log path")
        assert log_path.exists()
    finally:
        _close_logger(logger)
