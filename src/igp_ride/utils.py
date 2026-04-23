from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_config_path, user_data_path, user_log_path


APP_NAME = "igp-ride"

MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 3

_logging_initialized = False


def get_config_dir() -> Path:
    if sys.platform != "win32":
        return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    return Path(user_config_path(APP_NAME, appauthor=False, ensure_exists=False))


def get_data_dir() -> Path:
    if sys.platform != "win32":
        return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    return Path(user_data_path(APP_NAME, appauthor=False, ensure_exists=False))


def get_log_dir() -> Path:
    if sys.platform != "win32":
        return get_data_dir() / "logs"
    return Path(user_log_path(APP_NAME, appauthor=False, ensure_exists=False))


def get_log_file() -> Path:
    return get_log_dir() / f"{APP_NAME}.log"


def setup_logging() -> None:
    """Configure the igp_ride package logger exactly once."""
    global _logging_initialized
    if _logging_initialized:
        return
    _logging_initialized = True

    logger = logging.getLogger("igp_ride")
    logger.setLevel(logging.DEBUG)

    # Console handler: WARNING and above to stderr
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console_handler)

    # File handler: DEBUG and above with rotation
    try:
        log_dir = get_log_dir()
        log_file = get_log_file()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError:
        pass


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def format_distance(distance_meters: float) -> str:
    return f"{distance_meters / 1000:.1f} km"


def format_duration(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
