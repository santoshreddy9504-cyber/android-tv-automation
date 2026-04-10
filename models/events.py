"""
Event models for the Android TV monitoring system.
All inter-module communication uses these structured event objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class IssueCategory(str, Enum):
    CRASH = "CRASH"
    NETWORK = "NETWORK"
    PLAYBACK = "PLAYBACK"
    UI = "UI"
    PERFORMANCE = "PERFORMANCE"
    SYSTEM = "SYSTEM"


class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class IssueEvent:
    """Represents a detected issue during monitoring."""
    category: IssueCategory
    severity: IssueSeverity
    title: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw_log: str = ""
    screenshot_path: Optional[str] = None
    log_path: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "raw_log": self.raw_log,
            "screenshot_path": self.screenshot_path,
            "log_path": self.log_path,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        return (
            f"[{self.severity.value}] [{self.category.value}] "
            f"{self.title}: {self.message}"
        )


@dataclass
class PerformanceSnapshot:
    """Point-in-time performance metrics from the device."""
    timestamp: datetime = field(default_factory=datetime.now)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    janky_frames: int = 0
    total_frames: int = 0
    frame_drop_percent: float = 0.0
    app_pid: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "memory_percent": self.memory_percent,
            "janky_frames": self.janky_frames,
            "total_frames": self.total_frames,
            "frame_drop_percent": self.frame_drop_percent,
            "app_pid": self.app_pid,
        }


@dataclass
class SessionStats:
    """Aggregated statistics for a monitoring session."""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_issues: int = 0
    issues_by_category: dict = field(default_factory=dict)
    issues_by_severity: dict = field(default_factory=dict)
    crash_count: int = 0
    restart_count: int = 0
    avg_cpu: float = 0.0
    avg_memory_mb: float = 0.0
    peak_cpu: float = 0.0
    peak_memory_mb: float = 0.0
    all_events: list = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    def record_event(self, event: IssueEvent):
        self.total_issues += 1
        cat = event.category.value
        sev = event.severity.value
        self.issues_by_category[cat] = self.issues_by_category.get(cat, 0) + 1
        self.issues_by_severity[sev] = self.issues_by_severity.get(sev, 0) + 1
        if event.category == IssueCategory.CRASH:
            self.crash_count += 1
        self.all_events.append(event.to_dict())

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_issues": self.total_issues,
            "issues_by_category": self.issues_by_category,
            "issues_by_severity": self.issues_by_severity,
            "crash_count": self.crash_count,
            "restart_count": self.restart_count,
            "avg_cpu": round(self.avg_cpu, 2),
            "avg_memory_mb": round(self.avg_memory_mb, 2),
            "peak_cpu": round(self.peak_cpu, 2),
            "peak_memory_mb": round(self.peak_memory_mb, 2),
        }
