"""
Logging setup for the Android TV Automation system.
Provides colour console output + rotating file handler.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime

from config import LOGS_DIR


def setup_logging(level: str = "INFO", session_id: str = "") -> None:
    """
    Configure root logger with:
    - Coloured console handler (INFO and above)
    - Rotating file handler (DEBUG and above)
    """
    os.makedirs(LOGS_DIR, exist_ok=True)

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # capture everything, handlers filter

    # Remove existing handlers
    root.handlers.clear()

    # --- Console handler ---
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric_level)
    console.setFormatter(_ColorFormatter())
    root.addHandler(console)

    # --- File handler ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"_{session_id}" if session_id else ""
    log_file = os.path.join(LOGS_DIR, f"session{label}_{ts}.log")

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=20 * 1024 * 1024,   # 20 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ("urllib3", "requests", "werkzeug", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info(f"Logging initialised → {log_file}")


class _ColorFormatter(logging.Formatter):
    """Console formatter with ANSI colour codes per log level."""

    _COLORS = {
        logging.DEBUG:    "\033[2m",      # dim
        logging.INFO:     "\033[0m",      # normal
        logging.WARNING:  "\033[93m",     # yellow
        logging.ERROR:    "\033[91m",     # red
        logging.CRITICAL: "\033[1;91m",   # bold red
    }
    _RESET = "\033[0m"
    _FMT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    _DATE = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno, "")
        formatter = logging.Formatter(
            f"{color}{self._FMT}{self._RESET}",
            datefmt=self._DATE,
        )
        return formatter.format(record)
