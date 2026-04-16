"""
Release Gate — automatically decides if a build is safe to release.

Compares current session results vs baseline (previous build).
Makes a GO / NO-GO decision with full justification.

Checks:
  - Crash rate vs baseline
  - Memory peak vs baseline
  - Load time vs SLA and baseline
  - Frame drops vs threshold
  - New crash types not seen before

Also generates:
  - Release recommendation report
  - Build comparison table
  - Regression list (things that got worse)
  - Improvement list (things that got better)

Usage:
    gate = ReleaseGate()
    gate.save_baseline(session_stats, test_results)

    # Next build:
    gate.load_baseline()
    verdict = gate.evaluate(new_session_stats, new_test_results)
    print(verdict.decision)   # "GO" or "NO-GO"
    print(verdict.summary)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

BASELINE_FILE = "output/release_baseline.json"


@dataclass
class BuildMetrics:
    """Snapshot of metrics for one build/session."""
    build_id: str
    timestamp: datetime
    app_name: str

    # Core metrics
    crash_count: int = 0
    crash_rate_per_hour: float = 0.0
    peak_memory_mb: float = 0.0
    avg_memory_mb: float = 0.0
    peak_cpu: float = 0.0
    peak_frame_drop_pct: float = 0.0
    duration_seconds: float = 0.0

    # Load times
    cold_start_seconds: float = 0.0
    video_start_seconds: float = 0.0
    search_seconds: float = 0.0

    # Test results
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_blocked: int = 0
    pass_rate: float = 0.0

    # Crash types seen
    crash_types: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BuildMetrics":
        d = d.copy()
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)


@dataclass
class ReleaseVerdict:
    """Final GO/NO-GO decision."""
    decision: str               # "GO" | "NO-GO" | "CONDITIONAL GO"
    confidence: float           # 0.0–1.0
    summary: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Detailed findings
    blockers: List[str] = field(default_factory=list)      # NO-GO reasons
    warnings: List[str] = field(default_factory=list)      # Concerns
    improvements: List[str] = field(default_factory=list)  # Things better than baseline
    regressions: List[str] = field(default_factory=list)   # Things worse than baseline

    # Metrics
    current: Optional[BuildMetrics] = None
    baseline: Optional[BuildMetrics] = None

    def to_html(self) -> str:
        decision_colors = {"GO": "#16a34a", "NO-GO": "#dc2626", "CONDITIONAL GO": "#ca8a04"}
        decision_icons = {"GO": "✅", "NO-GO": "🚫", "CONDITIONAL GO": "⚠️"}
        color = decision_colors.get(self.decision, "#6b7280")
        icon = decision_icons.get(self.decision, "•")

        blockers_html = "".join(
            f'<li style="color:#ff5555; margin-bottom:6px;">{b}</li>'
            for b in self.blockers
        )
        warnings_html = "".join(
            f'<li style="color:#ffb86c; margin-bottom:6px;">{w}</li>'
            for w in self.warnings
        )
        improvements_html = "".join(
            f'<li style="color:#50fa7b; margin-bottom:6px;">{i}</li>'
            for i in self.improvements
        )
        regressions_html = "".join(
            f'<li style="color:#ff5555; margin-bottom:6px;">{r}</li>'
            for r in self.regressions
        )

        # Comparison table
        comparison = ""
        if self.current and self.baseline:
            c = self.current
            b = self.baseline

            def delta(cur, base, lower_is_better=True):
                if base == 0:
                    return ""
                pct = ((cur - base) / base) * 100
                if lower_is_better:
                    color = "#dc2626" if pct > 10 else ("#16a34a" if pct < -10 else "#f8f8f2")
                    arrow = "↑" if pct > 0 else "↓"
                else:
                    color = "#16a34a" if pct > 10 else ("#dc2626" if pct < -10 else "#f8f8f2")
                    arrow = "↑" if pct > 0 else "↓"
                return f'<span style="color:{color}; font-size:12px;">{arrow}{abs(pct):.0f}%</span>'

            rows = [
                ("Crashes", f"{c.crash_count}", f"{b.crash_count}", True),
                ("Crash Rate/hr", f"{c.crash_rate_per_hour:.2f}", f"{b.crash_rate_per_hour:.2f}", True),
                ("Peak Memory", f"{c.peak_memory_mb:.0f}MB", f"{b.peak_memory_mb:.0f}MB", True),
                ("Cold Start", f"{c.cold_start_seconds:.1f}s", f"{b.cold_start_seconds:.1f}s", True),
                ("Video Start", f"{c.video_start_seconds:.1f}s", f"{b.video_start_seconds:.1f}s", True),
                ("Frame Drops", f"{c.peak_frame_drop_pct:.1f}%", f"{b.peak_frame_drop_pct:.1f}%", True),
                ("Pass Rate", f"{c.pass_rate:.1f}%", f"{b.pass_rate:.1f}%", False),
            ]

            comparison = f"""
            <h3 style="color:#bd93f9;">Build Comparison</h3>
            <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
              <thead>
                <tr style="background:#2a2a3e;">
                  <th style="padding:10px; text-align:left; color:#6272a4;">Metric</th>
                  <th style="padding:10px; color:#6272a4;">Current Build</th>
                  <th style="padding:10px; color:#6272a4;">Baseline</th>
                  <th style="padding:10px; color:#6272a4;">Change</th>
                </tr>
              </thead>
              <tbody style="color:#f8f8f2;">
                {"".join(f'<tr><td style="padding:10px;">{name}</td><td style="padding:10px; text-align:center;">{cur}</td><td style="padding:10px; text-align:center; color:#6272a4;">{base}</td><td style="padding:10px; text-align:center;">{delta(self.current.__dict__.get(name.lower().replace(" ","_").replace("/","_per_"), 0), self.baseline.__dict__.get(name.lower().replace(" ","_").replace("/","_per_"), 0), lower) if self.current and self.baseline else ""}</td></tr>' for name, cur, base, lower in rows)}
              </tbody>
            </table>"""

        return f"""
        <div style="background:#1e1e2e; border-radius:12px; padding:24px; margin:16px 0;
                    font-family:sans-serif; border:3px solid {color};">
          <div style="display:flex; align-items:center; gap:20px; margin-bottom:20px;">
            <div style="background:{color}; border-radius:12px; padding:12px 24px;
                        font-size:28px; font-weight:bold; color:white; letter-spacing:2px;">
              {icon} {self.decision}
            </div>
            <div>
              <div style="color:#f8f8f2; font-size:18px;">{self.summary}</div>
              <div style="color:#6272a4; font-size:13px; margin-top:4px;">
                Confidence: {self.confidence*100:.0f}% | {self.timestamp.strftime('%Y-%m-%d %H:%M')}
              </div>
            </div>
          </div>

          {comparison}

          {f'<div style="margin-bottom:16px;"><h3 style="color:#dc2626; margin-bottom:8px;">🚫 Blockers (Must Fix Before Release)</h3><ul style="margin:0; padding-left:20px;">{blockers_html}</ul></div>' if self.blockers else ''}
          {f'<div style="margin-bottom:16px;"><h3 style="color:#dc2626; margin-bottom:8px;">📉 Regressions</h3><ul style="margin:0; padding-left:20px;">{regressions_html}</ul></div>' if self.regressions else ''}
          {f'<div style="margin-bottom:16px;"><h3 style="color:#ffb86c; margin-bottom:8px;">⚠ Warnings</h3><ul style="margin:0; padding-left:20px;">{warnings_html}</ul></div>' if self.warnings else ''}
          {f'<div><h3 style="color:#50fa7b; margin-bottom:8px;">✅ Improvements</h3><ul style="margin:0; padding-left:20px;">{improvements_html}</ul></div>' if self.improvements else ''}
        </div>
        """


class ReleaseGate:
    """
    Evaluates whether the current build is safe to release.
    Compares against a saved baseline from a previous good build.
    """

    # Thresholds for automatic NO-GO
    MAX_CRASH_RATE_PER_HOUR = 2.0       # More than 2 crashes/hr = NO-GO
    MAX_MEMORY_MB = 450.0               # > 450MB = NO-GO
    MAX_FRAME_DROP_PCT = 20.0           # > 20% janky frames = NO-GO
    MAX_COLD_START_S = 15.0             # > 15s cold start = NO-GO
    MIN_PASS_RATE = 60.0                # < 60% test pass rate = NO-GO

    # Regression thresholds (% worse than baseline)
    REGRESSION_CRASH_RATE_PCT = 50.0   # 50% more crashes/hr
    REGRESSION_MEMORY_PCT = 30.0       # 30% more memory
    REGRESSION_LOAD_TIME_PCT = 50.0    # 50% slower load times

    def __init__(self, baseline_file: str = BASELINE_FILE):
        self._baseline_file = baseline_file
        self._baseline: Optional[BuildMetrics] = None

    def save_baseline(self, metrics: BuildMetrics):
        """Save current build metrics as the new baseline."""
        os.makedirs(os.path.dirname(self._baseline_file), exist_ok=True)
        with open(self._baseline_file, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        self._baseline = metrics
        logger.info(f"Baseline saved: {metrics.build_id}")

    def load_baseline(self) -> bool:
        """Load saved baseline. Returns True if found."""
        if not os.path.exists(self._baseline_file):
            logger.warning("No baseline found — first run, all results accepted")
            return False
        try:
            with open(self._baseline_file) as f:
                data = json.load(f)
            self._baseline = BuildMetrics.from_dict(data)
            logger.info(f"Baseline loaded: {self._baseline.build_id}")
            return True
        except Exception as exc:
            logger.error(f"Failed to load baseline: {exc}")
            return False

    def evaluate(self, current: BuildMetrics) -> ReleaseVerdict:
        """
        Evaluate current build against thresholds and baseline.
        Returns a GO / NO-GO verdict.
        """
        verdict = ReleaseVerdict(
            decision="GO",
            confidence=1.0,
            current=current,
            baseline=self._baseline,
        )

        # ── Absolute threshold checks (always apply) ───────────────────
        if current.crash_rate_per_hour > self.MAX_CRASH_RATE_PER_HOUR:
            verdict.blockers.append(
                f"Crash rate {current.crash_rate_per_hour:.1f}/hr exceeds limit "
                f"({self.MAX_CRASH_RATE_PER_HOUR}/hr)"
            )
        if current.peak_memory_mb > self.MAX_MEMORY_MB:
            verdict.blockers.append(
                f"Peak memory {current.peak_memory_mb:.0f}MB exceeds limit "
                f"({self.MAX_MEMORY_MB:.0f}MB)"
            )
        if current.peak_frame_drop_pct > self.MAX_FRAME_DROP_PCT:
            verdict.blockers.append(
                f"Frame drops {current.peak_frame_drop_pct:.1f}% exceeds limit "
                f"({self.MAX_FRAME_DROP_PCT:.0f}%)"
            )
        if current.cold_start_seconds > self.MAX_COLD_START_S:
            verdict.blockers.append(
                f"Cold start {current.cold_start_seconds:.1f}s exceeds limit "
                f"({self.MAX_COLD_START_S:.0f}s)"
            )
        if current.tests_total > 0 and current.pass_rate < self.MIN_PASS_RATE:
            verdict.blockers.append(
                f"Test pass rate {current.pass_rate:.1f}% below minimum "
                f"({self.MIN_PASS_RATE:.0f}%)"
            )

        # ── Baseline regression checks ─────────────────────────────────
        if self._baseline:
            b = self._baseline

            def pct_change(cur, base):
                return ((cur - base) / max(base, 0.001)) * 100

            # Crash rate regression
            crash_delta = pct_change(current.crash_rate_per_hour, b.crash_rate_per_hour)
            if crash_delta > self.REGRESSION_CRASH_RATE_PCT and current.crash_count > 0:
                verdict.regressions.append(
                    f"Crash rate +{crash_delta:.0f}% vs baseline "
                    f"({current.crash_rate_per_hour:.2f} vs {b.crash_rate_per_hour:.2f}/hr)"
                )

            # Memory regression
            mem_delta = pct_change(current.peak_memory_mb, b.peak_memory_mb)
            if mem_delta > self.REGRESSION_MEMORY_PCT:
                verdict.regressions.append(
                    f"Peak memory +{mem_delta:.0f}% vs baseline "
                    f"({current.peak_memory_mb:.0f}MB vs {b.peak_memory_mb:.0f}MB)"
                )

            # Load time regressions
            if current.cold_start_seconds > 0 and b.cold_start_seconds > 0:
                cs_delta = pct_change(current.cold_start_seconds, b.cold_start_seconds)
                if cs_delta > self.REGRESSION_LOAD_TIME_PCT:
                    verdict.regressions.append(
                        f"Cold start +{cs_delta:.0f}% slower vs baseline "
                        f"({current.cold_start_seconds:.1f}s vs {b.cold_start_seconds:.1f}s)"
                    )

            # New crash types
            new_types = set(current.crash_types) - set(b.crash_types)
            for ct in new_types:
                verdict.regressions.append(f"New crash type not in baseline: {ct}")

            # Improvements
            if current.peak_memory_mb < b.peak_memory_mb * 0.9:
                verdict.improvements.append(
                    f"Memory improved: {current.peak_memory_mb:.0f}MB vs {b.peak_memory_mb:.0f}MB"
                )
            if current.crash_rate_per_hour < b.crash_rate_per_hour * 0.8:
                verdict.improvements.append(
                    f"Crash rate improved: {current.crash_rate_per_hour:.2f} vs {b.crash_rate_per_hour:.2f}/hr"
                )
            if (current.cold_start_seconds > 0 and b.cold_start_seconds > 0 and
                    current.cold_start_seconds < b.cold_start_seconds * 0.9):
                verdict.improvements.append(
                    f"Cold start faster: {current.cold_start_seconds:.1f}s vs {b.cold_start_seconds:.1f}s"
                )
            if current.pass_rate > b.pass_rate + 5:
                verdict.improvements.append(
                    f"Test pass rate improved: {current.pass_rate:.1f}% vs {b.pass_rate:.1f}%"
                )

        # Warnings (not blockers)
        if current.peak_memory_mb > 300:
            verdict.warnings.append(
                f"Memory at {current.peak_memory_mb:.0f}MB — approaching crash threshold of 420MB"
            )
        if current.crash_count > 0 and current.crash_count <= 2:
            verdict.warnings.append(
                f"{current.crash_count} crash(es) detected — monitor in production"
            )

        # ── Final decision ─────────────────────────────────────────────
        if verdict.blockers:
            verdict.decision = "NO-GO"
            verdict.confidence = 0.95
            verdict.summary = (
                f"Build BLOCKED — {len(verdict.blockers)} blocker(s) must be fixed. "
                f"Do NOT release."
            )
        elif verdict.regressions:
            verdict.decision = "CONDITIONAL GO"
            verdict.confidence = 0.7
            verdict.summary = (
                f"{len(verdict.regressions)} regression(s) detected. "
                f"Review before releasing."
            )
        else:
            verdict.decision = "GO"
            verdict.confidence = 0.95
            verdict.summary = (
                f"Build approved for release. "
                f"{len(verdict.improvements)} improvement(s) vs baseline."
            )

        logger.info(
            f"Release Gate: {verdict.decision} | "
            f"Blockers: {len(verdict.blockers)} | "
            f"Regressions: {len(verdict.regressions)}"
        )
        return verdict

    @property
    def baseline(self) -> Optional[BuildMetrics]:
        return self._baseline
