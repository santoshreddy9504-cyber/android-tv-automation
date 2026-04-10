"""
Timing Monitor — measures real load times, video start times, and
buffering durations by analysing logcat events in real time.

What it tracks
--------------
1. App launch time          — Android's "ActivityManager: Displayed" log
2. Activity / screen loads  — every new Activity display time from AM
3. Video startup time       — ExoPlayer STATE_BUFFERING → STATE_READY
4. Buffering during playback— STATE_BUFFERING while already playing
5. API response times       — OkHttp/Retrofit request → response pairs
6. Section content load     — watched section names appearing in logs
"""

import re
import time
import uuid
import logging
from collections import deque
from datetime import datetime
from typing import Optional, Dict

from config import config
from models.test_results import (
    TestCase, TestCategory, TestStatus,
    BufferingEvent, TestSuite,
)

logger = logging.getLogger(__name__)

# ── Android ActivityManager display time ────────────────────────────────────
# "ActivityManager: Displayed com.webnexs.rod_tv/.SomeActivity: +1s234ms"
_AM_DISPLAYED = re.compile(
    r"ActivityManager.*Displayed\s+([\w./$]+)\s*:\s*\+?([\d]+m?s[\d]*m?s?)",
    re.IGNORECASE,
)
# Parse "+2s123ms" or "+456ms" or "+1s"
_TIME_FULL  = re.compile(r"(\d+)s(\d+)ms")   # 2s123ms
_TIME_SEC   = re.compile(r"(\d+)s$")          # 2s
_TIME_MS    = re.compile(r"(\d+)ms$")         # 456ms

# ── ExoPlayer state transitions ─────────────────────────────────────────────
_EXO_BUFFERING = re.compile(r"ExoPlayer.*STATE_BUFFERING|playbackState.*=.*2\b", re.IGNORECASE)
_EXO_READY     = re.compile(r"ExoPlayer.*STATE_READY|playbackState.*=.*3\b",     re.IGNORECASE)
_EXO_PLAYING   = re.compile(r"ExoPlayer.*playWhenReady.*true|onIsPlayingChanged.*true", re.IGNORECASE)
_EXO_ENDED     = re.compile(r"ExoPlayer.*STATE_ENDED|playbackState.*=.*4\b",     re.IGNORECASE)
_EXO_IDLE      = re.compile(r"ExoPlayer.*STATE_IDLE|playbackState.*=.*1\b",      re.IGNORECASE)
_EXO_PREPARE   = re.compile(r"ExoPlayer.*setMediaItem|ExoPlayer.*prepare\(\)|MediaPlayer.*prepareAsync", re.IGNORECASE)

# ── Fragment transitions (Jetpack Navigation / Standard Fragments) ──────────
_FRAGMENT_DISPLAYED = re.compile(
    r"FragmentManager.*onFragmentStarted|NavGraph.*navigation.*to\s+([\w./$]+)|"
    r"NavController.*navigate\s+to\s+([\w./$]+)|Fragment\s+([\w./$]+)\s+started",
    re.IGNORECASE,
)

# ── Remote Control KeyEvents ────────────────────────────────────────────────
_KEY_EVENT = re.compile(
    r"ViewRootImpl.*dispatchKeyEvent\s+KeyEvent.*action=(?:ACTION_UP|1).*keycode=(\d+)|"
    r"WindowInputEventReceiver.*dispatchInputEvent.*KeyEvent.*keycode=(\d+)",
    re.IGNORECASE,
)

# ── Generic player patterns (non-ExoPlayer apps) ────────────────────────────
_PLAYER_START  = re.compile(r"onPrepared|MediaPlayer.*start\(\)|VideoPlayer.*start", re.IGNORECASE)
_PLAYER_BUFFER = re.compile(r"onBufferingUpdate|bufferingStart|BUFFERING_STARTED", re.IGNORECASE)
_PLAYER_READY  = re.compile(r"bufferingEnd|BUFFERING_ENDED|onVideoStarted|VideoStarted", re.IGNORECASE)

# ── OkHttp / Retrofit timing ─────────────────────────────────────────────────
_OKHTTP_REQ    = re.compile(r"OkHttp.*--> (GET|POST|PUT|DELETE|PATCH)\s+(\S+)", re.IGNORECASE)
_OKHTTP_RESP   = re.compile(r"OkHttp.*<-- (\d+)\s+.*\s+(\d+)ms", re.IGNORECASE)

# ── Section content signals ──────────────────────────────────────────────────
_CONTENT_LOADED = re.compile(
    r"(?:data|items|content|result).*(?:loaded|received|ready|success)|"
    r"(?:loaded|received|ready|success).*(?:data|items|content|result)|"
    r"RecyclerView.*notifyDataSetChanged|Adapter.*notifyDataSetChanged|"
    r"setData|bindData|submitList",
    re.IGNORECASE,
)

# Thresholds (ms) — adjust to your SLA requirements
THRESHOLDS = {
    TestCategory.APP_LAUNCH:   8000,
    TestCategory.SECTION_LOAD: 4000,
    TestCategory.VIDEO_START:  5000,
    TestCategory.BUFFERING:    3000,
    TestCategory.API_CALL:     3000,
    TestCategory.NAVIGATION:   2000,
}


def _parse_am_time(raw: str) -> Optional[float]:
    """Parse Android ActivityManager time string to milliseconds."""
    raw = raw.strip().lstrip("+")
    m = _TIME_FULL.search(raw)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2))
    m = _TIME_SEC.search(raw)
    if m:
        return int(m.group(1)) * 1000
    m = _TIME_MS.search(raw)
    if m:
        return int(m.group(1))
    return None


class TimingMonitor:
    """
    Analyses logcat lines for timing signals.
    All completed TestCase objects are stored in the shared TestSuite.
    """

    def __init__(self, suite: TestSuite):
        self._suite = suite
        self._package = config.app.package_name

        # State tracking
        self._video_prepare_time: Optional[datetime] = None
        self._video_playing = False
        self._current_buffering: Optional[BufferingEvent] = None
        self._pending_sections: Dict[str, TestCase] = {}
        self._pending_http: Dict[str, TestCase] = {}
        self._app_launched_at: Optional[datetime] = None
        self._launch_recorded = False

        # Signal response tracking
        self._last_key_press_time: Optional[datetime] = None
        self._last_key_code: Optional[str] = None

        # Mark app launch start
        self._app_launched_at = datetime.now()
        logger.info("TimingMonitor ready")

    def analyze(self, line: str):
        """Route each logcat line through all timing detectors."""
        self._check_key_event(line)
        self._check_am_displayed(line)
        self._check_fragment_transition(line)
        self._check_exoplayer(line)
        self._check_generic_player(line)
        self._check_content_loaded(line)
        self._check_okhttp(line)

    # ── Activity / screen load times ──────────────────────────────────────

    def _check_am_displayed(self, line: str):
        m = _AM_DISPLAYED.search(line)
        if not m:
            return

        component = m.group(1)   # e.g. com.webnexs.rod_tv/.HomeActivity
        time_str  = m.group(2)

        # Only track this app's activities
        if self._package not in component:
            return

        duration_ms = _parse_am_time(time_str)
        if duration_ms is None:
            return

        # Friendly activity name
        activity = component.split("/")[-1].lstrip(".")
        activity = activity.replace("Activity", "").replace("Fragment", "")

        # First displayed = app launch
        if not self._launch_recorded:
            self._launch_recorded = True
            tc = TestCase(
                id=str(uuid.uuid4())[:8],
                category=TestCategory.APP_LAUNCH,
                name="App Cold Start",
                started_at=self._app_launched_at or datetime.now(),
                threshold_ms=THRESHOLDS[TestCategory.APP_LAUNCH],
                raw_log=line,
            )
            tc.ended_at = datetime.now()
            tc.duration_ms = duration_ms
            tc.status = (
                TestStatus.SLOW if duration_ms > tc.threshold_ms else TestStatus.PASS
            )
            self._suite.add_test(tc)
            logger.info(f"[TIMING] App launch: {duration_ms:.0f}ms → {tc.status.value}")
        else:
            # Subsequent activities = navigation / section load
            tc = TestCase(
                id=str(uuid.uuid4())[:8],
                category=TestCategory.SECTION_LOAD,
                name=f"{activity} Screen",
                threshold_ms=THRESHOLDS[TestCategory.SECTION_LOAD],
                raw_log=line,
                metadata={"component": component},
            )
            tc.ended_at = datetime.now()
            tc.duration_ms = duration_ms
            tc.status = (
                TestStatus.SLOW if duration_ms > tc.threshold_ms else TestStatus.PASS
            )
            self._suite.add_test(tc)
            logger.info(f"[TIMING] Screen '{activity}': {duration_ms:.0f}ms → {tc.status.value}")

            # If we had a pending keypress, calculate input-to-display latency
            if self._last_key_press_time:
                latency = (datetime.now() - self._last_key_press_time).total_seconds() * 1000
                logger.info(f"[TIMING] Input response latency: {latency:.0f}ms (Key {self._last_key_code})")
                self._last_key_press_time = None

    # ── Fragment transitions ───────────────────────────────────────────

    def _check_fragment_transition(self, line: str):
        m = _FRAGMENT_DISPLAYED.search(line)
        if not m:
            return

        fragment = next(f for f in m.groups() if f)  # get first non-None group
        name = fragment.split(".")[-1].replace("Fragment", "")

        tc = TestCase(
            id=str(uuid.uuid4())[:8],
            category=TestCategory.NAVIGATION,
            name=f"Fragment: {name}",
            threshold_ms=THRESHOLDS[TestCategory.NAVIGATION],
            raw_log=line,
            metadata={"fragment": fragment},
        )
        tc.ended_at = datetime.now()
        # Fragments don't have a reliable 'Displayed' log with time,
        # so we use duration since last key press or navigation start if available.
        if self._last_key_press_time:
            tc.duration_ms = (datetime.now() - self._last_key_press_time).total_seconds() * 1000
        else:
            tc.duration_ms = 0 # unknown

        tc.status = (
            TestStatus.SLOW if tc.duration_ms > tc.threshold_ms else TestStatus.PASS
        )
        self._suite.add_test(tc)
        logger.info(f"[TIMING] Fragment '{name}': {tc.duration_ms:.0f}ms → {tc.status.value}")
        self._last_key_press_time = None

    # ── Remote Control Latency ────────────────────────────────────────

    def _check_key_event(self, line: str):
        m = _KEY_EVENT.search(line)
        if m:
            self._last_key_code = next(k for k in m.groups() if k)
            self._last_key_press_time = datetime.now()
            logger.debug(f"[TIMING] Remote key {self._last_key_code} detected")

    # ── ExoPlayer state machine ───────────────────────────────────────────

    def _check_exoplayer(self, line: str):
        if _EXO_PREPARE.search(line):
            self._video_prepare_time = datetime.now()
            self._video_playing = False
            logger.debug("[TIMING] Video prepare started")

        elif _EXO_BUFFERING.search(line):
            if self._video_playing:
                # Buffering mid-playback
                if not self._current_buffering:
                    self._current_buffering = BufferingEvent()
                    logger.debug("[TIMING] Mid-playback buffering started")
            # else: initial buffer before playback starts — tracked by video start timer

        elif _EXO_READY.search(line) or _EXO_PLAYING.search(line):
            # Stop any mid-playback buffering
            if self._current_buffering:
                self._current_buffering.stop()
                self._suite.add_buffering(self._current_buffering)
                logger.info(
                    f"[TIMING] Buffering ended: {self._current_buffering.duration_ms:.0f}ms"
                )
                self._current_buffering = None

            # Record video start time
            if not self._video_playing and self._video_prepare_time:
                duration_ms = (datetime.now() - self._video_prepare_time).total_seconds() * 1000
                self._video_playing = True
                tc = TestCase(
                    id=str(uuid.uuid4())[:8],
                    category=TestCategory.VIDEO_START,
                    name="Video Playback Start",
                    started_at=self._video_prepare_time,
                    threshold_ms=THRESHOLDS[TestCategory.VIDEO_START],
                    raw_log=line,
                )
                tc.ended_at = datetime.now()
                tc.duration_ms = duration_ms
                tc.status = (
                    TestStatus.SLOW if duration_ms > tc.threshold_ms else TestStatus.PASS
                )
                self._suite.add_test(tc)
                logger.info(f"[TIMING] Video start: {duration_ms:.0f}ms → {tc.status.value}")
                self._video_prepare_time = None

        elif _EXO_ENDED.search(line) or _EXO_IDLE.search(line):
            self._video_playing = False
            if self._current_buffering:
                self._current_buffering.stop()
                self._suite.add_buffering(self._current_buffering)
                self._current_buffering = None

    # ── Generic MediaPlayer fallback ──────────────────────────────────────

    def _check_generic_player(self, line: str):
        if _PLAYER_START.search(line) and self._package in line:
            if not self._video_prepare_time:
                self._video_prepare_time = datetime.now()
                logger.debug("[TIMING] Generic player prepare detected")

        elif _PLAYER_BUFFER.search(line) and self._package in line:
            if self._video_playing and not self._current_buffering:
                self._current_buffering = BufferingEvent()

        elif _PLAYER_READY.search(line) and self._package in line:
            if self._current_buffering:
                self._current_buffering.stop()
                self._suite.add_buffering(self._current_buffering)
                self._current_buffering = None

            if not self._video_playing and self._video_prepare_time:
                duration_ms = (datetime.now() - self._video_prepare_time).total_seconds() * 1000
                self._video_playing = True
                tc = TestCase(
                    id=str(uuid.uuid4())[:8],
                    category=TestCategory.VIDEO_START,
                    name="Video Playback Start",
                    started_at=self._video_prepare_time,
                    threshold_ms=THRESHOLDS[TestCategory.VIDEO_START],
                    raw_log=line,
                )
                tc.ended_at = datetime.now()
                tc.duration_ms = duration_ms
                tc.status = (
                    TestStatus.SLOW if duration_ms > tc.threshold_ms else TestStatus.PASS
                )
                self._suite.add_test(tc)
                logger.info(f"[TIMING] Video start (generic): {duration_ms:.0f}ms → {tc.status.value}")
                self._video_prepare_time = None

    # ── Content / section data loaded ─────────────────────────────────────

    def _check_content_loaded(self, line: str):
        if not _CONTENT_LOADED.search(line):
            return
        if self._package not in line:
            return

        # Check if any watched section is pending
        for section_name, tc in list(self._pending_sections.items()):
            if tc.status == TestStatus.PENDING:
                tc.finish()
                self._suite.add_test(tc)
                del self._pending_sections[section_name]
                logger.info(
                    f"[TIMING] Section '{section_name}' loaded: "
                    f"{tc.duration_ms:.0f}ms → {tc.status.value}"
                )

    def start_section_load(self, section_name: str):
        """Called externally when a watched section navigation is detected."""
        tc = TestCase(
            id=str(uuid.uuid4())[:8],
            category=TestCategory.SECTION_LOAD,
            name=f'Section: "{section_name}"',
            threshold_ms=THRESHOLDS[TestCategory.SECTION_LOAD],
            metadata={"section": section_name},
        )
        self._pending_sections[section_name] = tc
        logger.debug(f"[TIMING] Section load timer started: {section_name}")

    # ── OkHttp request/response timing ────────────────────────────────────

    def _check_okhttp(self, line: str):
        m = _OKHTTP_RESP.search(line)
        if m:
            status_code = m.group(1)
            duration_ms = float(m.group(2))
            status = (
                TestStatus.FAIL if status_code.startswith(("4", "5"))
                else TestStatus.SLOW if duration_ms > THRESHOLDS[TestCategory.API_CALL]
                else TestStatus.PASS
            )
            tc = TestCase(
                id=str(uuid.uuid4())[:8],
                category=TestCategory.API_CALL,
                name=f"API {status_code}",
                threshold_ms=THRESHOLDS[TestCategory.API_CALL],
                raw_log=line,
                metadata={"http_code": status_code, "duration_ms": duration_ms},
            )
            tc.duration_ms = duration_ms
            tc.status = status
            tc.ended_at = datetime.now()
            if status == TestStatus.FAIL:
                tc.failure_reason = f"HTTP {status_code}"
            self._suite.add_test(tc)
            logger.debug(f"[TIMING] API call: {status_code} {duration_ms:.0f}ms → {status.value}")

    # ── Finalize any open timers ──────────────────────────────────────────

    def finalize(self):
        """Close any open timers at session end (mark PENDING as inconclusive)."""
        for tc in self._pending_sections.values():
            if tc.status == TestStatus.PENDING:
                tc.status = TestStatus.FAIL
                tc.failure_reason = "Section did not finish loading before session ended"
                self._suite.add_test(tc)

        if self._current_buffering:
            self._current_buffering.stop()
            self._suite.add_buffering(self._current_buffering)
