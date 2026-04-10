"""
Test result models — section load tests, playback tests, navigation tests.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class TestStatus(str, Enum):
    PASS    = "PASS"
    FAIL    = "FAIL"
    SLOW    = "SLOW"      # loaded but exceeded threshold
    PENDING = "PENDING"   # started, not yet resolved


class TestCategory(str, Enum):
    APP_LAUNCH   = "App Launch"
    SECTION_LOAD = "Section Load"
    VIDEO_START  = "Video Start"
    BUFFERING    = "Buffering"
    NAVIGATION   = "Navigation"
    API_CALL     = "API Call"


@dataclass
class TestCase:
    """A single timed test observation."""
    id: str
    category: TestCategory
    name: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    status: TestStatus = TestStatus.PENDING
    duration_ms: Optional[float] = None
    threshold_ms: float = 3000.0        # SLA threshold
    failure_reason: str = ""
    raw_log: str = ""
    metadata: dict = field(default_factory=dict)

    def finish(self, ended_at: Optional[datetime] = None, failed: bool = False, reason: str = ""):
        self.ended_at = ended_at or datetime.now()
        self.duration_ms = (self.ended_at - self.started_at).total_seconds() * 1000
        if failed:
            self.status = TestStatus.FAIL
            self.failure_reason = reason
        elif self.duration_ms > self.threshold_ms:
            self.status = TestStatus.SLOW
        else:
            self.status = TestStatus.PASS

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category.value,
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 1) if self.duration_ms else None,
            "threshold_ms": self.threshold_ms,
            "failure_reason": self.failure_reason,
            "raw_log": self.raw_log,
            "metadata": self.metadata,
        }


@dataclass
class BufferingEvent:
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    duration_ms: Optional[float] = None

    def stop(self):
        self.ended_at = datetime.now()
        self.duration_ms = (self.ended_at - self.started_at).total_seconds() * 1000

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": round(self.duration_ms, 1) if self.duration_ms else None,
        }


@dataclass
class TestSuite:
    """All test results for a session."""
    session_id: str
    app_package: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    test_cases: List[TestCase] = field(default_factory=list)
    buffering_events: List[BufferingEvent] = field(default_factory=list)

    # Summary counters
    @property
    def total(self) -> int:
        return len([t for t in self.test_cases if t.status != TestStatus.PENDING])

    @property
    def passed(self) -> int:
        return len([t for t in self.test_cases if t.status == TestStatus.PASS])

    @property
    def failed(self) -> int:
        return len([t for t in self.test_cases if t.status == TestStatus.FAIL])

    @property
    def slow(self) -> int:
        return len([t for t in self.test_cases if t.status == TestStatus.SLOW])

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100

    @property
    def avg_load_ms(self) -> float:
        times = [t.duration_ms for t in self.test_cases
                 if t.duration_ms and t.status != TestStatus.FAIL]
        return sum(times) / len(times) if times else 0.0

    @property
    def total_buffering_ms(self) -> float:
        return sum(b.duration_ms or 0 for b in self.buffering_events)

    @property
    def buffering_count(self) -> int:
        return len(self.buffering_events)

    def add_test(self, test: TestCase):
        self.test_cases.append(test)

    def add_buffering(self, event: BufferingEvent):
        self.buffering_events.append(event)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "app_package": self.app_package,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "slow": self.slow,
            "pass_rate": round(self.pass_rate, 1),
            "avg_load_ms": round(self.avg_load_ms, 1),
            "buffering_count": self.buffering_count,
            "total_buffering_ms": round(self.total_buffering_ms, 1),
            "test_cases": [t.to_dict() for t in self.test_cases],
            "buffering_events": [b.to_dict() for b in self.buffering_events],
        }
