"""
Playback Monitor — detects video playback issues, DRM errors,
buffering problems, and player failures.
"""

import re
import time
from collections import deque
from datetime import datetime

from models.events import IssueEvent, IssueCategory, IssueSeverity


# ExoPlayer / MediaPlayer patterns
_EXO_ERROR = re.compile(
    r"ExoPlaybackException|com\.google\.android\.exoplayer2.*[Ee]rror",
    re.IGNORECASE,
)
_MEDIA_PLAYER_ERROR = re.compile(
    r"MediaPlayer.*error|VideoView.*error|MediaSession.*error",
    re.IGNORECASE,
)
_DRM_ERROR = re.compile(
    r"DrmSession.*error|MediaDrm.*error|DRM.*fail|"
    r"WidevineError|LICENSE.*fail|KeyRequest.*fail|"
    r"com\.widevine|drm.*exception",
    re.IGNORECASE,
)
_BUFFERING = re.compile(
    r"bufferingStart|onBufferingUpdate|BUFFERING_STARTED|"
    r"BufferingStrategy|PlayerState\.BUFFERING",
    re.IGNORECASE,
)
_BUFFERING_END = re.compile(
    r"bufferingEnd|BUFFERING_ENDED|PlayerState\.READY",
    re.IGNORECASE,
)
_STALL = re.compile(
    r"VideoStall|PlaybackStall|stalled|STALL",
    re.IGNORECASE,
)
_CONTENT_LOAD_FAIL = re.compile(
    r"LoadError|DataSourceException|HttpDataSource.*error|"
    r"UnexpectedLoaderException",
    re.IGNORECASE,
)
_SEEK_ERROR = re.compile(
    r"SeekException|seek.*failed|seek.*error",
    re.IGNORECASE,
)
_AUDIO_ERROR = re.compile(
    r"AudioTrack.*error|AudioSink.*error|AudioProcessor.*error",
    re.IGNORECASE,
)


class PlaybackMonitor:
    """
    Scans logcat for playback-related errors and emits events.
    Tracks buffering start/end to calculate buffer duration.
    """

    def __init__(self, session, buffer: deque):
        self._session = session
        self._buffer = buffer
        self._buffering_start: float = 0.0
        self._is_buffering = False
        self._last_emit_time: dict = {}
        self._dedup_window = 10.0   # seconds per pattern

    def analyze(self, line: str):
        if _DRM_ERROR.search(line):
            self._emit_once(
                key="drm",
                title="DRM Error",
                message=line.strip(),
                severity=IssueSeverity.CRITICAL,
                raw=line,
                metadata={"drm_line": line},
            )

        elif _EXO_ERROR.search(line):
            self._emit_once(
                key="exo",
                title="ExoPlayer Error",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _MEDIA_PLAYER_ERROR.search(line):
            self._emit_once(
                key="media_player",
                title="MediaPlayer Error",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _CONTENT_LOAD_FAIL.search(line):
            self._emit_once(
                key="load_fail",
                title="Content Load Failure",
                message=line.strip(),
                severity=IssueSeverity.HIGH,
                raw=line,
            )

        elif _BUFFERING.search(line) and not self._is_buffering:
            self._is_buffering = True
            self._buffering_start = time.time()

        elif _BUFFERING_END.search(line) and self._is_buffering:
            buffer_duration = time.time() - self._buffering_start
            self._is_buffering = False
            if buffer_duration > 5.0:   # only alert on sustained buffering
                self._emit_once(
                    key="buffer",
                    title="Sustained Buffering",
                    message=f"Buffering lasted {buffer_duration:.1f}s",
                    severity=IssueSeverity.MEDIUM,
                    raw=line,
                    metadata={"buffer_duration_s": round(buffer_duration, 2)},
                )

        elif _STALL.search(line):
            self._emit_once(
                key="stall",
                title="Playback Stall",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

        elif _SEEK_ERROR.search(line):
            self._emit_once(
                key="seek",
                title="Seek Error",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

        elif _AUDIO_ERROR.search(line):
            self._emit_once(
                key="audio",
                title="Audio Error",
                message=line.strip(),
                severity=IssueSeverity.MEDIUM,
                raw=line,
            )

    def _emit_once(
        self, key: str, title: str, message: str,
        severity: IssueSeverity, raw: str, metadata: dict = None
    ):
        """Emit event with per-key deduplication."""
        now = time.time()
        if now - self._last_emit_time.get(key, 0) < self._dedup_window:
            return
        self._last_emit_time[key] = now

        event = IssueEvent(
            category=IssueCategory.PLAYBACK,
            severity=severity,
            title=title,
            message=message,
            timestamp=datetime.now(),
            raw_log=raw,
            metadata=metadata or {},
        )
        self._session.event_queue.put(event)
