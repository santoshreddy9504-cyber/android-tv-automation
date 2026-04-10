"""
Network Monitor — detects API failures, timeouts, and connectivity issues.
"""

import re
import time
from collections import deque
from datetime import datetime

from models.events import IssueEvent, IssueCategory, IssueSeverity


# HTTP 4xx / 5xx — require word-bounded 3-digit codes to avoid matching
# dates/timestamps embedded in logcat lines (e.g. "0409" in the header).
_HTTP_4XX = re.compile(
    r"HTTP[/\s]\S*?\s+4\d\d\b"                 # HTTP/1.1 401 Unauthorized
    r"|\bstatus[_\s]*code[=:\s]+4\d\d\b"        # status_code=403
    r"|\bcode[=:\s]+4\d\d\b"                    # code=404
    r"|\berror.{0,10}4[0-9]{2}\b"               # error: 401
    r"|\b4[0-9]{2}\b.{0,20}\berror\b",          # 401 ... error
    re.IGNORECASE,
)
_HTTP_5XX = re.compile(
    r"HTTP[/\s]\S*?\s+5\d\d\b"                 # HTTP/1.1 500
    r"|\bstatus[_\s]*code[=:\s]+5\d\d\b"        # status_code=503
    r"|\bcode[=:\s]+5\d\d\b"                    # code=500
    r"|\bserver.{0,10}\berror\b"                # server error
    r"|\berror.{0,10}5[0-9]{2}\b"               # error: 500
    r"|\b5[0-9]{2}\b.{0,20}\berror\b",          # 503 ... error
    re.IGNORECASE,
)
_HTTP_CODE = re.compile(r"\b([45]\d{2})\b")

# Timeout patterns
_TIMEOUT = re.compile(
    r"ConnectTimeoutException|SocketTimeoutException|ReadTimeoutException|"
    r"Connection timed out|timeout.*connect|connect.*timeout|"
    r"TimeoutException",
    re.IGNORECASE,
)

# Connection errors
_CONNECTION_REFUSED = re.compile(
    r"Connection refused|ConnectException|ECONNREFUSED",
    re.IGNORECASE,
)
_NO_NETWORK = re.compile(
    r"UnknownHostException|Unable to resolve host|Network is unreachable|"
    r"No route to host|EHOSTUNREACH|ENETUNREACH",
    re.IGNORECASE,
)

# TLS/SSL
_SSL_ERROR = re.compile(
    r"SSLException|SSLHandshakeException|SSL.*error|Certificate.*error|"
    r"javax\.net\.ssl",
    re.IGNORECASE,
)

# Retrofit / OkHttp / Volley
_RETROFIT = re.compile(
    r"retrofit2.*error|OkHttp.*error|Volley.*error|"
    r"NetworkResponse.*error|RetrofitError",
    re.IGNORECASE,
)

# Generic API error keywords
_API_ERROR = re.compile(
    r"API.*error|api_error|ApiException|RestException|"
    r"GraphQL.*error|grpc.*error",
    re.IGNORECASE,
)


class NetworkMonitor:
    """
    Analyses logcat lines for network / API failure patterns.
    """

    def __init__(self, session, buffer: deque):
        self._session = session
        self._buffer = buffer
        self._last_emit: dict = {}
        self._dedup_window = 15.0

    def analyze(self, line: str):
        if _NO_NETWORK.search(line):
            self._emit_once(
                key="no_network",
                title="No Network / DNS Failure",
                message=line.strip(),
                severity=IssueSeverity.CRITICAL,
                raw=line,
            )

        elif _SSL_ERROR.search(line):
            self._emit_once(
                key="ssl",
                title="SSL / TLS Error",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _TIMEOUT.search(line):
            self._emit_once(
                key="timeout",
                title="Network Timeout",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _HTTP_5XX.search(line):
            code = self._extract_http_code(line) or "5xx"
            self._emit_once(
                key=f"http_{code}",
                title=f"Server Error (HTTP {code})",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
                metadata={"http_code": code},
            )

        elif _HTTP_4XX.search(line):
            code = self._extract_http_code(line) or "4xx"
            severity = (
                IssueSeverity.MEDIUM if str(code) == "404"
                else IssueSeverity.HIGH
            )
            self._emit_once(
                key=f"http_{code}",
                title=f"Client Error (HTTP {code})",
                message=line.strip(),
                severity=severity,
                raw=line,
                metadata={"http_code": code},
            )

        elif _CONNECTION_REFUSED.search(line):
            self._emit_once(
                key="conn_refused",
                title="Connection Refused",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _API_ERROR.search(line):
            self._emit_once(
                key="api_error",
                title="API Error",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

        elif _RETROFIT.search(line):
            self._emit_once(
                key="retrofit",
                title="HTTP Client Error",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

    def _extract_http_code(self, line: str) -> str:
        m = _HTTP_CODE.search(line)
        return m.group(1) if m else ""

    def _emit_once(
        self, key: str, title: str, message: str,
        severity: IssueSeverity, raw: str, metadata: dict = None
    ):
        now = time.time()
        if now - self._last_emit.get(key, 0) < self._dedup_window:
            return
        self._last_emit[key] = now

        event = IssueEvent(
            category=IssueCategory.NETWORK,
            severity=severity,
            title=title,
            message=message,
            timestamp=datetime.now(),
            raw_log=raw,
            metadata=metadata or {},
        )
        self._session.event_queue.put(event)
