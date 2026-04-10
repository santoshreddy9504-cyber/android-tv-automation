"""
Log Handler — saves relevant logcat context to timestamped files
whenever an issue is detected.
"""

import os
import logging
from datetime import datetime
from typing import List

from config import config, LOGS_DIR
from models.events import IssueEvent

logger = logging.getLogger(__name__)

# Reference to the active LogcatMonitor (set by session bootstrap)
_logcat_monitor_ref = None


def register_logcat_monitor(monitor):
    """Called during session setup to give log handler access to the buffer."""
    global _logcat_monitor_ref
    _logcat_monitor_ref = monitor


class LogHandler:
    """
    Saves a snippet of the logcat buffer (N lines before + after)
    to a .log file for every qualifying issue event.
    """

    def __init__(self):
        os.makedirs(LOGS_DIR, exist_ok=True)

    def handle(self, event: IssueEvent, adb=None):
        if not config.alert.save_logs_on_issue:
            return

        try:
            log_path = self._write_log(event)
            if log_path:
                event.log_path = log_path
        except Exception as exc:
            logger.error(f"Log handler error: {exc}")

    def _write_log(self, event: IssueEvent) -> str:
        """Build and write the log file. Returns file path."""
        path = self._build_path(event)

        context_lines: List[str] = []
        if _logcat_monitor_ref:
            n = config.alert.log_context_lines
            context_lines = _logcat_monitor_ref.get_context_lines(n)

        with open(path, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write(f"ANDROID TV AUTOMATION — ISSUE LOG\n")
            f.write("=" * 70 + "\n")
            f.write(f"Timestamp  : {event.timestamp.isoformat()}\n")
            f.write(f"Category   : {event.category.value}\n")
            f.write(f"Severity   : {event.severity.value}\n")
            f.write(f"Title      : {event.title}\n")
            f.write(f"Message    : {event.message}\n")

            if event.metadata:
                f.write(f"Metadata   : {event.metadata}\n")

            f.write("\n--- RAW TRIGGER LINE ---\n")
            f.write(event.raw_log + "\n")

            f.write(f"\n--- LOGCAT CONTEXT (last {len(context_lines)} lines) ---\n")
            for line in context_lines:
                f.write(line + "\n")

            f.write("\n" + "=" * 70 + "\n")

        logger.debug(f"Log saved: {path}")
        return path

    def _build_path(self, event: IssueEvent) -> str:
        ts = event.timestamp.strftime("%Y%m%d_%H%M%S")
        cat = event.category.value.lower()
        sev = event.severity.value.lower()
        title = event.title.replace(" ", "_").replace("/", "-")[:40]
        filename = f"{ts}_{cat}_{sev}_{title}.log"
        return os.path.join(LOGS_DIR, filename)
