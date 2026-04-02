from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


XDG_DATA_HOME = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
LOG_DIR = XDG_DATA_HOME / "igp-ride" / "logs"
LOG_FILE = LOG_DIR / "igp-ride.log"

MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 3

_logging_initialized = False


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
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE,
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
