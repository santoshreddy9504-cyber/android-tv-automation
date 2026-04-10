"""
Performance Monitor — polls CPU, memory, and gfxinfo (frame drops)
at a configurable interval and emits IssueEvents when thresholds breach.
"""

import time
import logging
from datetime import datetime

from config import config
from models.events import IssueEvent, IssueCategory, IssueSeverity, PerformanceSnapshot
from monitors.base_monitor import BaseMonitor

logger = logging.getLogger(__name__)


class PerformanceMonitor(BaseMonitor):
    """
    Runs in its own thread, polling device metrics every
    config.monitor.performance_poll_interval seconds.
    """

    def __init__(self, session):
        super().__init__(session)
        self._package = config.app.package_name
        self._cpu_alert_count = 0
        self._mem_alert_count = 0
        # Require N consecutive breaches before alerting (reduce noise)
        self._consecutive_threshold = 2

    def run(self):
        self._log.info("Performance monitor starting ...")
        interval = config.monitor.performance_poll_interval

        while not self._stop.is_set():
            try:
                snapshot = self._collect()
                if snapshot:
                    self._session.record_performance(snapshot)
                    self._evaluate(snapshot)
            except Exception as exc:
                self._log.warning(f"Performance poll error: {exc}")

            # Sleep in small chunks so we respond quickly to stop signal
            for _ in range(interval):
                if self._stop.is_set():
                    break
                time.sleep(1)

        self._log.info("Performance monitor stopped.")

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _collect(self) -> PerformanceSnapshot:
        package = self._package
        pid = self._adb.get_app_pid(package)

        cpu = self._adb.get_cpu_usage(package)
        mem_mb, mem_pct = self._adb.get_memory_usage(package)
        gfx = self._adb.get_gfxinfo(package)

        snapshot = PerformanceSnapshot(
            timestamp=datetime.now(),
            cpu_percent=cpu,
            memory_mb=mem_mb,
            memory_percent=mem_pct,
            janky_frames=gfx.get("janky_frames", 0),
            total_frames=gfx.get("total_frames", 0),
            frame_drop_percent=gfx.get("frame_drop_pct", 0.0),
            app_pid=pid,
        )

        self._log.debug(
            f"CPU: {cpu:.1f}% | MEM: {mem_mb:.0f}MB | "
            f"Janky: {gfx.get('janky_frames', 0)}/{gfx.get('total_frames', 0)}"
        )
        return snapshot

    # ------------------------------------------------------------------
    # Threshold evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, snap: PerformanceSnapshot):
        self._check_cpu(snap)
        self._check_memory(snap)
        self._check_frame_drops(snap)

    def _check_cpu(self, snap: PerformanceSnapshot):
        threshold = config.monitor.cpu_alert_threshold
        if snap.cpu_percent >= threshold:
            self._cpu_alert_count += 1
            if self._cpu_alert_count >= self._consecutive_threshold:
                self._cpu_alert_count = 0
                self.emit(IssueEvent(
                    category=IssueCategory.PERFORMANCE,
                    severity=IssueSeverity.HIGH,
                    title="High CPU Usage",
                    message=(
                        f"CPU at {snap.cpu_percent:.1f}% "
                        f"(threshold: {threshold}%)"
                    ),
                    timestamp=snap.timestamp,
                    metadata=snap.to_dict(),
                ))
        else:
            self._cpu_alert_count = max(0, self._cpu_alert_count - 1)

    def _check_memory(self, snap: PerformanceSnapshot):
        threshold_mb = config.monitor.memory_alert_threshold_mb
        if snap.memory_mb >= threshold_mb:
            self._mem_alert_count += 1
            if self._mem_alert_count >= self._consecutive_threshold:
                self._mem_alert_count = 0
                severity = (
                    IssueSeverity.CRITICAL
                    if snap.memory_mb >= threshold_mb * 1.5
                    else IssueSeverity.HIGH
                )
                self.emit(IssueEvent(
                    category=IssueCategory.PERFORMANCE,
                    severity=severity,
                    title="High Memory Usage",
                    message=(
                        f"Memory at {snap.memory_mb:.0f}MB "
                        f"(threshold: {threshold_mb}MB)"
                    ),
                    timestamp=snap.timestamp,
                    metadata=snap.to_dict(),
                ))
        else:
            self._mem_alert_count = max(0, self._mem_alert_count - 1)

    def _check_frame_drops(self, snap: PerformanceSnapshot):
        threshold = config.monitor.frame_drop_alert_threshold
        if (snap.total_frames > 100 and
                snap.frame_drop_percent >= threshold):
            self.emit(IssueEvent(
                category=IssueCategory.UI,
                severity=IssueSeverity.MEDIUM,
                title="Frame Drops Detected",
                message=(
                    f"{snap.janky_frames}/{snap.total_frames} janky frames "
                    f"({snap.frame_drop_percent:.1f}% — threshold {threshold}%)"
                ),
                timestamp=snap.timestamp,
                metadata=snap.to_dict(),
            ))
