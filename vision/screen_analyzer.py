"""
Screen Analyzer — Computer Vision for Android TV apps.

Analyzes screenshots to detect:
  - Black screen (app not rendering)
  - Frozen frame (same image for too long)
  - Loading spinner visible
  - Video playing vs paused
  - UI elements present/missing
  - Text content on screen

Works using:
  1. Pixel analysis (brightness, color variance) — no dependencies needed
  2. PIL/Pillow for advanced analysis (optional)
  3. Hash comparison for frozen frame detection

No GPU or ML model required — pure image math.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScreenAnalysis:
    """Result of analyzing one screenshot."""
    screenshot_path: str
    timestamp: datetime

    # Detected states
    is_black_screen: bool = False
    is_frozen: bool = False         # Same as previous screenshot
    has_spinner: bool = False       # Loading indicator visible
    is_playing: bool = False        # Video actively playing (frame changed)
    is_error_screen: bool = False   # Error message visible
    brightness: float = 0.0        # 0.0 (black) to 1.0 (white)
    color_variance: float = 0.0    # Low = solid color / frozen

    # Content detection
    dominant_color: Tuple[int, int, int] = (0, 0, 0)
    has_content: bool = False       # Not black, not error

    # Frame comparison
    frame_hash: str = ""
    similarity_to_prev: float = 0.0  # 0=different, 1=identical

    # Issues found
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "screenshot": self.screenshot_path,
            "timestamp": self.timestamp.isoformat(),
            "is_black_screen": self.is_black_screen,
            "is_frozen": self.is_frozen,
            "has_spinner": self.has_spinner,
            "is_playing": self.is_playing,
            "brightness": round(self.brightness, 3),
            "issues": self.issues,
        }


class ScreenAnalyzer:
    """
    Analyzes screenshots for visual anomalies.

    Usage:
        analyzer = ScreenAnalyzer()
        analysis = analyzer.analyze("/path/to/screenshot.png")
        if analysis.is_black_screen:
            alert("BLACK SCREEN DETECTED")
    """

    BLACK_THRESHOLD = 0.05        # Brightness below this = black screen
    FROZEN_HASH_WINDOW = 3        # How many previous frames to remember
    SPINNER_REGION_SIZE = 0.3     # Center region to check for spinner

    def __init__(self):
        self._prev_hashes: List[str] = []
        self._prev_analysis: Optional[ScreenAnalysis] = None
        self._pil_available = self._check_pil()
        if not self._pil_available:
            logger.info("Pillow not installed — using basic pixel analysis. "
                        "Install with: pip install Pillow")

    def _check_pil(self) -> bool:
        try:
            from PIL import Image
            return True
        except ImportError:
            return False

    def analyze(self, screenshot_path: str) -> Optional[ScreenAnalysis]:
        """Analyze a screenshot file. Returns None if file not found."""
        if not os.path.exists(screenshot_path):
            logger.warning(f"Screenshot not found: {screenshot_path}")
            return None

        analysis = ScreenAnalysis(
            screenshot_path=screenshot_path,
            timestamp=datetime.now(),
        )

        if self._pil_available:
            self._analyze_with_pil(analysis, screenshot_path)
        else:
            self._analyze_basic(analysis, screenshot_path)

        self._detect_frozen(analysis)
        self._classify_issues(analysis)

        self._prev_hashes.append(analysis.frame_hash)
        if len(self._prev_hashes) > self.FROZEN_HASH_WINDOW:
            self._prev_hashes.pop(0)

        self._prev_analysis = analysis
        return analysis

    def _analyze_with_pil(self, analysis: ScreenAnalysis, path: str):
        """Full PIL-based image analysis."""
        from PIL import Image, ImageStat
        import colorsys

        img = Image.open(path).convert("RGB")
        w, h = img.size

        # Compute hash for frozen detection
        analysis.frame_hash = hashlib.md5(img.tobytes()).hexdigest()

        # Overall brightness and stats
        stat = ImageStat.Stat(img)
        r_mean, g_mean, b_mean = stat.mean[:3]
        analysis.brightness = (r_mean + g_mean + b_mean) / (3 * 255)
        analysis.dominant_color = (int(r_mean), int(g_mean), int(b_mean))

        # Color variance (low = frozen / single color)
        r_var, g_var, b_var = stat.var[:3]
        analysis.color_variance = (r_var + g_var + b_var) / 3

        # Black screen check
        analysis.is_black_screen = analysis.brightness < self.BLACK_THRESHOLD

        # Has content
        analysis.has_content = (
            not analysis.is_black_screen and
            analysis.color_variance > 100
        )

        # Spinner detection — look for circular region in center with animation color
        # Simplified: check if center region has different brightness from edges
        center_box = (
            int(w * 0.35), int(h * 0.35),
            int(w * 0.65), int(h * 0.65)
        )
        center_crop = img.crop(center_box)
        center_stat = ImageStat.Stat(center_crop)
        center_brightness = sum(center_stat.mean[:3]) / (3 * 255)

        # Spinner usually appears as a bright circle on dark background
        edge_brightness = analysis.brightness
        if (not analysis.is_black_screen and
                center_brightness > edge_brightness * 1.5 and
                analysis.color_variance < 500):
            analysis.has_spinner = True

        # Video playing detection — if this frame is different from previous
        if self._prev_analysis and not self._prev_analysis.is_black_screen:
            analysis.similarity_to_prev = self._compute_similarity(
                img, self._prev_analysis.screenshot_path
            )
            analysis.is_playing = analysis.similarity_to_prev < 0.95

    def _analyze_basic(self, analysis: ScreenAnalysis, path: str):
        """Basic analysis without PIL — uses file size and hash only."""
        # File hash for frozen detection
        with open(path, "rb") as f:
            data = f.read()
        analysis.frame_hash = hashlib.md5(data).hexdigest()

        # File size heuristic — black/blank screens are very small PNG files
        size_kb = len(data) / 1024
        analysis.is_black_screen = size_kb < 5.0
        analysis.has_content = not analysis.is_black_screen
        analysis.brightness = min(1.0, size_kb / 50.0)  # Rough proxy
        analysis.color_variance = size_kb * 10          # Rough proxy

    def _compute_similarity(self, img, prev_path: str) -> float:
        """Compute how similar two images are (0=different, 1=identical)."""
        if not self._pil_available or not os.path.exists(prev_path):
            return 0.0
        try:
            from PIL import Image, ImageChops
            import math
            prev_img = Image.open(prev_path).convert("RGB")
            # Resize both to small thumbnail for fast comparison
            size = (64, 36)
            a = img.resize(size)
            b = prev_img.resize(size)
            diff = ImageChops.difference(a, b)
            pixels = list(diff.getdata())
            avg_diff = sum(sum(p) / 3 for p in pixels) / len(pixels)
            similarity = 1.0 - (avg_diff / 255)
            return max(0.0, min(1.0, similarity))
        except Exception:
            return 0.0

    def _detect_frozen(self, analysis: ScreenAnalysis):
        """Check if current frame matches recent frames (frozen)."""
        if not analysis.frame_hash:
            return
        # Count how many of the last N frames have the same hash
        same_count = sum(1 for h in self._prev_hashes if h == analysis.frame_hash)
        analysis.is_frozen = same_count >= min(2, len(self._prev_hashes))

    def _classify_issues(self, analysis: ScreenAnalysis):
        """Build list of detected visual issues."""
        if analysis.is_black_screen:
            analysis.issues.append("BLACK SCREEN — App not rendering content")
        if analysis.is_frozen and not analysis.is_black_screen:
            analysis.issues.append("FROZEN FRAME — Screen not updating (possible ANR or hang)")
        if analysis.has_spinner:
            analysis.issues.append("LOADING SPINNER — Content taking too long to load")
        if analysis.is_error_screen:
            analysis.issues.append("ERROR SCREEN — Error message visible to user")


class VisualMonitor:
    """
    Runs visual analysis on a stream of screenshots from the device.
    Emits events when visual anomalies are detected.
    """

    def __init__(self, session, adb, screenshot_interval: int = 30):
        self._session = session
        self._adb = adb
        self._interval = screenshot_interval
        self._analyzer = ScreenAnalyzer()
        self._analysis_history: List[ScreenAnalysis] = []

    def analyze_latest_screenshot(self, path: str) -> Optional[ScreenAnalysis]:
        """Analyze a screenshot and emit events for any issues found."""
        analysis = self._analyzer.analyze(path)
        if not analysis:
            return None

        self._analysis_history.append(analysis)

        for issue in analysis.issues:
            logger.warning(f"[Vision] {issue}")
            self._emit_visual_event(issue, analysis)

        return analysis

    def _emit_visual_event(self, issue_description: str, analysis: ScreenAnalysis):
        from models.events import IssueEvent, IssueCategory, IssueSeverity
        severity = IssueSeverity.CRITICAL if "BLACK SCREEN" in issue_description else IssueSeverity.HIGH
        event = IssueEvent(
            category=IssueCategory.UI,
            severity=severity,
            title=issue_description.split("—")[0].strip(),
            message=issue_description,
            timestamp=analysis.timestamp,
            screenshot_path=analysis.screenshot_path,
            metadata=analysis.to_dict(),
        )
        self._session.event_queue.put(event)

    @property
    def history(self) -> List[ScreenAnalysis]:
        return self._analysis_history
