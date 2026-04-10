"""
API Monitor — captures live HTTP requests & responses from logcat.

Mimics Android Studio's Network Inspector by parsing OkHttp /
Retrofit2 / Volley log output that the app emits via logcat.

Captured for each call:
  • Method + URL
  • Request headers (optional)
  • HTTP status code
  • Response time (ms)
  • Response body size
  • Error message (if any)

Output:
  • In-memory log  → self.calls  (list of APICall)
  • Event queue    → fires NETWORK IssueEvent on 4xx / 5xx
  • JSON snapshot  → output/reports/api_calls_<session>.json
"""

import re
import time
import json
import os
import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict

from config import config, REPORTS_DIR
from models.events import IssueEvent, IssueCategory, IssueSeverity

logger = logging.getLogger(__name__)

# ── Regex patterns (OkHttp HttpLoggingInterceptor format) ────────────────────

# --> GET https://api.example.com/path (0-byte body)
_OKHTTP_REQ = re.compile(
    r"--> (?P<method>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(?P<url>https?://\S+)",
    re.IGNORECASE,
)

# <-- 200 https://api.example.com/path (123ms, 4096-byte body)
_OKHTTP_RESP = re.compile(
    r"<-- (?P<code>\d{3})\s+(?P<url>https?://\S+)\s+\((?P<ms>\d+)ms(?:,\s*(?P<bytes>\d+)-byte body)?\)",
    re.IGNORECASE,
)

# <-- HTTP FAILED: java.net.SocketTimeoutException
_OKHTTP_FAIL = re.compile(
    r"<-- HTTP FAILED:\s*(?P<error>.+)",
    re.IGNORECASE,
)

# Retrofit2:  retrofit2.Retrofit  BODY: { ... }
_RETROFIT_BODY = re.compile(r"retrofit2.*BODY:\s*(?P<body>.+)", re.IGNORECASE)

# Volley:  BasicNetwork.performRequest: Unexpected response code 403 for ...
_VOLLEY_CODE = re.compile(
    r"Unexpected response code\s+(?P<code>\d{3})\s+for\s+(?P<url>https?://\S+)",
    re.IGNORECASE,
)

# Generic URL pattern as fallback  (any logcat line containing https?://)
_GENERIC_URL = re.compile(r"(https?://[^\s\"'<>]+)", re.IGNORECASE)

# HTTP status code anywhere
_STATUS_CODE = re.compile(r"\b(?P<code>[245]\d{2})\b")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class APICall:
    timestamp: str
    method: str
    url: str
    status_code: int = 0           # 0 = unknown / in-flight
    response_ms: int = 0
    response_bytes: int = 0
    error: str = ""
    source: str = "logcat"         # okhttp / retrofit / volley / generic
    request_headers: Dict = field(default_factory=dict)
    response_summary: str = ""

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400 or bool(self.error)

    @property
    def status_label(self) -> str:
        if self.error:
            return "ERROR"
        if self.status_code == 0:
            return "PENDING"
        return str(self.status_code)


# ── Monitor class ─────────────────────────────────────────────────────────────

class APIMonitor:
    """
    Feed logcat lines to analyze().
    Maintains self.calls — queryable from tests and the report.
    """

    def __init__(self, session=None, max_calls: int = 500):
        self._session = session
        self._lock    = threading.Lock()
        self.calls: List[APICall] = []
        self._max    = max_calls
        self._pending: Dict[str, APICall] = {}   # url → in-flight request
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, line: str):
        """Call for every logcat line (runs in the logcat thread)."""
        try:
            self._try_okhttp(line)
            self._try_volley(line)
            self._try_generic(line)
        except Exception as exc:
            logger.debug(f"APIMonitor.analyze error: {exc}")

    def snapshot(self) -> List[APICall]:
        with self._lock:
            return list(self.calls)

    def errors(self) -> List[APICall]:
        return [c for c in self.snapshot() if c.is_error]

    def by_url(self, fragment: str) -> List[APICall]:
        frag = fragment.lower()
        return [c for c in self.snapshot() if frag in c.url.lower()]

    def stats(self) -> dict:
        calls = self.snapshot()
        total   = len(calls)
        success = sum(1 for c in calls if 200 <= c.status_code < 300)
        errors  = sum(1 for c in calls if c.is_error)
        avg_ms  = (sum(c.response_ms for c in calls if c.response_ms) /
                   max(1, sum(1 for c in calls if c.response_ms)))
        slow    = sum(1 for c in calls if c.response_ms > 3000)
        return {
            "total": total, "success": success,
            "errors": errors, "avg_ms": round(avg_ms),
            "slow_calls": slow,
        }

    def save_json(self) -> str:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.join(REPORTS_DIR, f"api_calls_{self._session_id}.json")
        with open(path, "w") as f:
            json.dump([asdict(c) for c in self.snapshot()], f, indent=2)
        return path

    # ── Internal parsers ──────────────────────────────────────────────────────

    def _try_okhttp(self, line: str):
        # Outgoing request
        m = _OKHTTP_REQ.search(line)
        if m:
            call = APICall(
                timestamp=datetime.now().isoformat(),
                method=m.group("method").upper(),
                url=m.group("url"),
                source="okhttp",
            )
            with self._lock:
                self._pending[call.url] = call
            return

        # Successful response
        m = _OKHTTP_RESP.search(line)
        if m:
            url   = m.group("url")
            code  = int(m.group("code"))
            ms    = int(m.group("ms"))
            size  = int(m.group("bytes") or 0)
            with self._lock:
                call = self._pending.pop(url, None)
                if call is None:
                    call = APICall(
                        timestamp=datetime.now().isoformat(),
                        method="GET",
                        url=url,
                        source="okhttp",
                    )
                call.status_code   = code
                call.response_ms   = ms
                call.response_bytes = size
                call.response_summary = f"HTTP {code} in {ms}ms ({size} bytes)"
            self._record(call)
            return

        # Failed request
        m = _OKHTTP_FAIL.search(line)
        if m:
            # We don't know which URL this belongs to — grab last pending
            error = m.group("error").strip()
            with self._lock:
                items = list(self._pending.items())
            if items:
                url, call = items[-1]
                call.error = error
                with self._lock:
                    self._pending.pop(url, None)
                self._record(call)

    def _try_volley(self, line: str):
        m = _VOLLEY_CODE.search(line)
        if m:
            call = APICall(
                timestamp=datetime.now().isoformat(),
                method="GET",
                url=m.group("url"),
                status_code=int(m.group("code")),
                source="volley",
            )
            self._record(call)

    def _try_generic(self, line: str):
        """Catch-all: any logcat line with a URL + HTTP code."""
        urls = _GENERIC_URL.findall(line)
        if not urls:
            return
        cm = _STATUS_CODE.search(line)
        if not cm:
            return
        code = int(cm.group("code"))
        # Only record if it looks like a response (has a meaningful code)
        if code < 200:
            return
        url = urls[0].rstrip(".,;)")
        # Avoid duplicate if already recorded by OkHttp parser
        with self._lock:
            recent_urls = {c.url for c in self.calls[-20:]}
        if url in recent_urls:
            return
        call = APICall(
            timestamp=datetime.now().isoformat(),
            method="GET",
            url=url,
            status_code=code,
            source="generic",
        )
        self._record(call)

    def _record(self, call: APICall):
        """Store and optionally emit an event for errors."""
        with self._lock:
            self.calls.append(call)
            if len(self.calls) > self._max:
                self.calls.pop(0)

        logger.debug(
            f"[API] {call.method} {call.url} → "
            f"{call.status_label} ({call.response_ms}ms)"
        )

        # Fire issue event for 4xx/5xx
        if self._session and call.is_error:
            severity = (IssueSeverity.CRITICAL if call.status_code in (401, 403, 500)
                        else IssueSeverity.HIGH if call.status_code >= 500
                        else IssueSeverity.MEDIUM)
            event = IssueEvent(
                category=IssueCategory.NETWORK,
                severity=severity,
                title=f"API Error {call.status_label}: {call.url.split('?')[0][-60:]}",
                message=call.error or f"HTTP {call.status_code} from {call.url}",
                timestamp=datetime.now(),
                raw_log="",
                metadata={
                    "url": call.url,
                    "method": call.method,
                    "status_code": call.status_code,
                    "response_ms": call.response_ms,
                },
            )
            self._session.event_queue.put(event)
