"""
Crash Predictor — predicts crashes BEFORE they happen.

Uses memory growth trend to forecast:
  - Time until next crash
  - Confidence level
  - Warning threshold (send alert before crash)

Algorithm:
  1. Track memory readings over time
  2. Fit linear regression on last N readings
  3. Extrapolate to crash threshold (400MB)
  4. Alert when < warning_minutes away from predicted crash

No ML library needed — uses pure Python linear regression.
"""

import time
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CrashPrediction:
    """Prediction result from the crash predictor."""
    timestamp: datetime
    current_memory_mb: float
    crash_threshold_mb: float

    # Prediction
    predicted_crash_at: Optional[datetime]
    minutes_until_crash: Optional[float]
    confidence: float             # 0.0–1.0

    # Trend
    growth_rate_mb_per_min: float
    is_growing: bool
    warning_level: str            # "safe" | "watch" | "warning" | "critical"

    def is_critical(self) -> bool:
        return self.warning_level in ("warning", "critical")

    def summary(self) -> str:
        if not self.predicted_crash_at or not self.is_growing:
            return f"Memory stable at {self.current_memory_mb:.0f}MB — no crash predicted"

        mins = self.minutes_until_crash
        if mins is None:
            return f"Memory at {self.current_memory_mb:.0f}MB — trend unclear"

        if mins < 2:
            return (f"CRITICAL: Crash imminent in ~{mins:.1f} min! "
                    f"Memory {self.current_memory_mb:.0f}MB growing {self.growth_rate_mb_per_min:.1f}MB/min")
        elif mins < 5:
            return (f"WARNING: Crash predicted in ~{mins:.1f} min. "
                    f"Memory {self.current_memory_mb:.0f}MB growing {self.growth_rate_mb_per_min:.1f}MB/min")
        else:
            return (f"Memory {self.current_memory_mb:.0f}MB, "
                    f"growing {self.growth_rate_mb_per_min:.1f}MB/min — "
                    f"crash in ~{mins:.1f} min if trend continues")

    def to_html_alert(self) -> str:
        colors = {"safe": "#16a34a", "watch": "#ca8a04",
                  "warning": "#ea580c", "critical": "#dc2626"}
        icons = {"safe": "✓", "watch": "⚠", "warning": "⚠️", "critical": "🚨"}
        color = colors.get(self.warning_level, "#6b7280")
        icon = icons.get(self.warning_level, "•")

        mins_str = f"~{self.minutes_until_crash:.1f} min" if self.minutes_until_crash else "unknown"
        crash_time = (self.predicted_crash_at.strftime('%H:%M:%S')
                      if self.predicted_crash_at else "N/A")

        return f"""
        <div style="background:#1e1e2e; border-left:4px solid {color}; border-radius:8px;
                    padding:16px; margin:12px 0; font-family:sans-serif;">
          <div style="color:{color}; font-weight:bold; font-size:14px; margin-bottom:8px;">
            {icon} CRASH PREDICTION — {self.warning_level.upper()}
          </div>
          <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px;">
            <div style="background:#2a2a3e; border-radius:6px; padding:10px; text-align:center;">
              <div style="color:#f8f8f2; font-size:18px; font-weight:bold;">{self.current_memory_mb:.0f}MB</div>
              <div style="color:#6272a4; font-size:10px;">Current RAM</div>
            </div>
            <div style="background:#2a2a3e; border-radius:6px; padding:10px; text-align:center;">
              <div style="color:#ffb86c; font-size:18px; font-weight:bold;">+{self.growth_rate_mb_per_min:.1f}MB/min</div>
              <div style="color:#6272a4; font-size:10px;">Growth Rate</div>
            </div>
            <div style="background:#2a2a3e; border-radius:6px; padding:10px; text-align:center;">
              <div style="color:{color}; font-size:18px; font-weight:bold;">{mins_str}</div>
              <div style="color:#6272a4; font-size:10px;">Time to Crash</div>
            </div>
            <div style="background:#2a2a3e; border-radius:6px; padding:10px; text-align:center;">
              <div style="color:#f8f8f2; font-size:18px; font-weight:bold;">{crash_time}</div>
              <div style="color:#6272a4; font-size:10px;">Predicted At</div>
            </div>
          </div>
          <div style="color:#6272a4; font-size:11px; margin-top:8px;">
            Confidence: {self.confidence*100:.0f}% | Crash threshold: {self.crash_threshold_mb:.0f}MB
          </div>
        </div>
        """


class CrashPredictor:
    """
    Monitors memory readings and predicts crash time using linear regression.

    Usage:
        predictor = CrashPredictor(crash_threshold_mb=420.0)
        predictor.add_reading(timestamp, memory_mb)
        prediction = predictor.predict()
        if prediction.is_critical():
            send_alert(prediction.summary())
    """

    def __init__(
        self,
        crash_threshold_mb: float = 420.0,
        warning_minutes: float = 5.0,
        min_readings: int = 5,
        window_readings: int = 20,
        on_warning: Optional[Callable] = None,
    ):
        self._threshold = crash_threshold_mb
        self._warning_minutes = warning_minutes
        self._min_readings = min_readings
        self._window = window_readings
        self._on_warning = on_warning

        # Store (unix_timestamp, memory_mb) tuples
        self._readings: List[Tuple[float, float]] = []
        self._last_alert_level = "safe"
        self._predictions: List[CrashPrediction] = []

    def add_reading(self, memory_mb: float, ts: Optional[float] = None):
        """Add a new memory reading."""
        t = ts or time.time()
        self._readings.append((t, memory_mb))

        # Keep only the last window
        if len(self._readings) > self._window:
            self._readings = self._readings[-self._window:]

    def predict(self) -> Optional[CrashPrediction]:
        """
        Compute crash prediction from current readings.
        Returns None if not enough data yet.
        """
        if len(self._readings) < self._min_readings:
            return None

        current_mem = self._readings[-1][1]
        now = time.time()

        # Linear regression on recent readings
        rate, intercept, r_squared = self._linear_regression(self._readings)

        # rate is MB/second — convert to MB/minute
        rate_per_min = rate * 60.0

        is_growing = rate > 0.001  # Threshold to avoid noise

        predicted_crash_at = None
        minutes_until_crash = None

        if is_growing and current_mem < self._threshold:
            # Time until memory hits threshold (in seconds from now)
            # threshold = intercept + rate * t  →  t = (threshold - intercept) / rate
            t_crash = (self._threshold - intercept) / rate
            seconds_until = t_crash - now

            if seconds_until > 0:
                minutes_until_crash = seconds_until / 60.0
                predicted_crash_at = datetime.now() + timedelta(seconds=seconds_until)

        # Determine warning level
        if not is_growing or minutes_until_crash is None:
            level = "safe"
        elif minutes_until_crash <= 2:
            level = "critical"
        elif minutes_until_crash <= self._warning_minutes:
            level = "warning"
        elif minutes_until_crash <= self._warning_minutes * 3:
            level = "watch"
        else:
            level = "safe"

        # Confidence based on R² of regression
        confidence = min(r_squared, 1.0) if r_squared > 0 else 0.3

        prediction = CrashPrediction(
            timestamp=datetime.now(),
            current_memory_mb=current_mem,
            crash_threshold_mb=self._threshold,
            predicted_crash_at=predicted_crash_at,
            minutes_until_crash=minutes_until_crash,
            confidence=confidence,
            growth_rate_mb_per_min=rate_per_min,
            is_growing=is_growing,
            warning_level=level,
        )

        self._predictions.append(prediction)

        # Fire callback if level escalated
        if level != self._last_alert_level and level in ("warning", "critical"):
            self._last_alert_level = level
            logger.warning(f"[CrashPredictor] {prediction.summary()}")
            if self._on_warning:
                try:
                    self._on_warning(prediction)
                except Exception as exc:
                    logger.error(f"Prediction callback error: {exc}")

        return prediction

    def _linear_regression(
        self, readings: List[Tuple[float, float]]
    ) -> Tuple[float, float, float]:
        """
        Simple ordinary least squares linear regression.
        Returns (slope, intercept, r_squared).
        slope is in MB/second.
        """
        n = len(readings)
        if n < 2:
            return 0.0, readings[0][1] if readings else 0.0, 0.0

        sum_x = sum(t for t, _ in readings)
        sum_y = sum(m for _, m in readings)
        sum_xx = sum(t * t for t, _ in readings)
        sum_xy = sum(t * m for t, m in readings)

        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-10:
            return 0.0, sum_y / n, 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        # R² calculation
        y_mean = sum_y / n
        ss_tot = sum((m - y_mean) ** 2 for _, m in readings)
        ss_res = sum((m - (slope * t + intercept)) ** 2 for t, m in readings)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 1e-10 else 0.0

        return slope, intercept, max(0.0, r_squared)

    def reset(self):
        """Clear readings — call after app restart."""
        self._readings.clear()
        self._last_alert_level = "safe"
        logger.info("CrashPredictor reset — memory baseline cleared")

    @property
    def latest_prediction(self) -> Optional[CrashPrediction]:
        return self._predictions[-1] if self._predictions else None

    @property
    def all_predictions(self) -> List[CrashPrediction]:
        return self._predictions


class PredictiveMonitorThread:
    """
    Wraps CrashPredictor in a background thread.
    Feeds memory readings from SessionManager automatically.
    """

    def __init__(self, predictor: CrashPredictor, session, poll_interval: int = 30):
        self._predictor = predictor
        self._session = session
        self._interval = poll_interval
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="PredictiveMonitor", daemon=True
        )
        self._thread.start()
        logger.info("Predictive crash monitor started")

    def _run(self):
        while not self._session.stop_event.is_set():
            snap = self._session.get_latest_performance()
            if snap:
                self._predictor.add_reading(snap.memory_mb)
                pred = self._predictor.predict()
                if pred and pred.is_critical():
                    # Inject warning into session event queue
                    self._inject_warning(pred)

            self._session.stop_event.wait(timeout=self._interval)

    def _inject_warning(self, pred: CrashPrediction):
        from models.events import IssueEvent, IssueCategory, IssueSeverity
        event = IssueEvent(
            category=IssueCategory.PERFORMANCE,
            severity=IssueSeverity.CRITICAL if pred.warning_level == "critical"
                     else IssueSeverity.HIGH,
            title=f"Crash Predicted in {pred.minutes_until_crash:.1f} min",
            message=pred.summary(),
            timestamp=pred.timestamp,
            metadata=pred.__dict__,
        )
        self._session.event_queue.put(event)
