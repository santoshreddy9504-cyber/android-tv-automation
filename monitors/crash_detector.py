"""
Crash Detector — identifies crashes, ANRs, fatal exceptions in logcat.
"""

import re
import time
from collections import deque
from datetime import datetime

from models.events import IssueEvent, IssueCategory, IssueSeverity


# Compile patterns once for performance
_FATAL_EXCEPTION = re.compile(
    r"E\s+AndroidRuntime.*FATAL EXCEPTION", re.IGNORECASE
)
_EXCEPTION_LINE = re.compile(
    r"E\s+AndroidRuntime.*(?:Exception|Error):", re.IGNORECASE
)
_ANR_LINE = re.compile(
    r"ANR in|Input dispatching timed out|Application Not Responding",
    re.IGNORECASE,
)
_PROCESS_DIED = re.compile(
    r"Process\s+\S+\s+has\s+(?:died|crashed)|Force finishing", re.IGNORECASE
)
_WATCHDOG = re.compile(r"WATCHDOG KILLING SYSTEM PROCESS", re.IGNORECASE)
_OOM = re.compile(r"OutOfMemoryError", re.IGNORECASE)
_NATIVE_CRASH = re.compile(r"SIGSEGV|SIGABRT|Fatal signal", re.IGNORECASE)


class CrashDetector:
    """
    Analyses logcat lines for crash/ANR/fatal patterns.
    Deduplicates rapid repeated crash events (1-second window).
    """

    def __init__(self, session, buffer: deque):
        self._session = session
        self._buffer = buffer
        self._last_crash_time: float = 0.0
        self._dedup_window = 5.0   # seconds

    def analyze(self, line: str):
        package = self._session.app._package

        if _FATAL_EXCEPTION.search(line):
            self._emit(
                title="Fatal Exception",
                message=line.strip(),
                severity=IssueSeverity.CRITICAL,
                raw=line,
            )

        elif _ANR_LINE.search(line) and package in line:
            self._emit(
                title="ANR Detected",
                message=f"App Not Responding: {line.strip()}",
                severity=IssueSeverity.CRITICAL,
                raw=line,
            )

        elif _PROCESS_DIED.search(line) and package in line:
            self._emit(
                title="Process Died",
                message=line.strip(),
                severity=IssueSeverity.CRITICAL,
                raw=line,
            )

        elif _OOM.search(line) and package in line:
            self._emit(
                title="Out of Memory",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _NATIVE_CRASH.search(line):
            self._emit(
                title="Native Crash",
                message=line.strip(),
                severity=IssueSeverity.CRITICAL,
                raw=line,
            )

        elif _WATCHDOG.search(line):
            self._emit(
                title="System Watchdog Kill",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _EXCEPTION_LINE.search(line) and package in line:
            self._emit(
                title="Unhandled Exception",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

    def _emit(self, title: str, message: str, severity: IssueSeverity, raw: str):
        """Emit event with deduplication."""
        now = time.time()
        if now - self._last_crash_time < self._dedup_window:
            return
        self._last_crash_time = now

        event = IssueEvent(
            category=IssueCategory.CRASH,
            severity=severity,
            title=title,
            message=message,
            timestamp=datetime.now(),
            raw_log=raw,
            metadata={"buffer_tail": list(self._buffer)[-20:]},
        )
        self._session.event_queue.put(event)
