"""
UI Monitor — detects UI loading failures, section load errors,
and general UI rendering issues in logcat.
"""

import re
import time
from collections import deque
from datetime import datetime

from config import config
from models.events import IssueEvent, IssueCategory, IssueSeverity


# Section/content load failures
_SECTION_FAIL = re.compile(
    r"section.*(?:fail|error|not.*load|timeout)|"
    r"(?:fail|error|not.*load|timeout).*section|"
    r"content.*(?:fail|error|empty)|"
    r"(?:fail|error).*content",
    re.IGNORECASE,
)
_LOAD_FAILURE = re.compile(
    r"LoadFailed|ImageLoadFailed|GlideException|PicassoException|"
    r"CoilException|failed to load",
    re.IGNORECASE,
)
_EMPTY_STATE = re.compile(
    r"EmptyView|empty.{0,20}state|zero.{0,10}items|"
    r"items.{0,10}empty|list.{0,10}empty",
    re.IGNORECASE,
)

# Navigation / Fragment errors
_FRAGMENT_ERROR = re.compile(
    r"FragmentException|Fragment.*not.*attached|"
    r"Activity.*destroyed|IllegalStateException.*fragment",
    re.IGNORECASE,
)
_NAV_ERROR = re.compile(
    r"NavigationException|Destination.*not found|"
    r"NavController.*error",
    re.IGNORECASE,
)

# Rendering / view errors
_VIEW_INFLATION = re.compile(
    r"InflateException|ClassNotFoundException.*View|"
    r"Binary XML.*Error",
    re.IGNORECASE,
)
_RESOURCE_NOT_FOUND = re.compile(
    r"ResourceNotFoundException|NotFoundException.*resource|"
    r"Resources\$NotFoundException",
    re.IGNORECASE,
)

# Focus / remote control issues
_FOCUS_ISSUE = re.compile(
    r"requestFocus.*failed|focus.*null|"
    r"ViewRootImpl.*focus",
    re.IGNORECASE,
)


def _build_section_pattern() -> re.Pattern:
    """Build pattern from configured watched sections."""
    sections = config.monitor.watched_sections
    if not sections:
        return re.compile(r"(?!)")  # never-match placeholder
    escaped = [re.escape(s) for s in sections]
    return re.compile(
        r"(?:" + "|".join(escaped) + r").*(?:fail|error|not.*load|timeout|empty)",
        re.IGNORECASE,
    )


class UIMonitor:
    """
    Detects UI-level failures by analysing logcat lines.
    """

    def __init__(self, session, buffer: deque):
        self._session = session
        self._buffer = buffer
        self._section_pattern = _build_section_pattern()
        self._last_emit: dict = {}
        self._dedup_window = 20.0

    def analyze(self, line: str):
        # Check watched sections first (highest priority for OTT QA)
        for section in config.monitor.watched_sections:
            if section.lower() in line.lower():
                if re.search(
                    r"fail|error|not.*load|timeout|empty|crash",
                    line, re.IGNORECASE
                ):
                    self._emit_once(
                        key=f"section_{section}",
                        title=f'Section Not Loading: "{section}"',
                        message=line.strip(),
                        severity=IssueSeverity.HIGH,
                        raw=line,
                        metadata={"section": section},
                    )
                    return

        if _VIEW_INFLATION.search(line):
            self._emit_once(
                key="inflate",
                title="View Inflation Error",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _FRAGMENT_ERROR.search(line):
            self._emit_once(
                key="fragment",
                title="Fragment Error",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _NAV_ERROR.search(line):
            self._emit_once(
                key="nav",
                title="Navigation Error",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

        elif _LOAD_FAILURE.search(line):
            self._emit_once(
                key="img_load",
                title="Image/Asset Load Failure",
                message=line.strip(),
                severity=IssueSeverity.LOW,
                raw=line,
            )

        elif _RESOURCE_NOT_FOUND.search(line):
            self._emit_once(
                key="resource",
                title="Resource Not Found",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

        elif _EMPTY_STATE.search(line):
            self._emit_once(
                key="empty",
                title="Empty Content State",
                message=line.strip(),
                severity=IssueSeverity.LOW,
                raw=line,
            )

    def _emit_once(
        self, key: str, title: str, message: str,
        severity: IssueSeverity, raw: str, metadata: dict = None
    ):
        now = time.time()
        if now - self._last_emit.get(key, 0) < self._dedup_window:
            return
        self._last_emit[key] = now

        event = IssueEvent(
            category=IssueCategory.UI,
            severity=severity,
            title=title,
            message=message,
            timestamp=datetime.now(),
            raw_log=raw,
            metadata=metadata or {},
        )
        self._session.event_queue.put(event)
