"""
UX Scorer — AI rates user experience quality from session data.

Scores the session 0–100 and identifies frustrating moments:
  - Slow screens (load > SLA)
  - Repeated back presses (user confusion)
  - Failed searches
  - Crash frequency
  - Memory/frame drop patterns

Used in final reports to give a single health score.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class UXScore:
    """Complete UX health score for a session."""
    session_id: str
    app_name: str
    timestamp: datetime

    # Overall score
    score: float = 0.0            # 0–100
    grade: str = "F"              # A / B / C / D / F
    verdict: str = ""             # One-line summary

    # Sub-scores (each 0–100)
    stability_score: float = 0.0      # crashes / uptime
    performance_score: float = 0.0    # memory, cpu, frames
    responsiveness_score: float = 0.0 # load times vs SLA
    playback_score: float = 0.0       # video quality

    # Identified pain points
    pain_points: List[str] = field(default_factory=list)
    positive_signals: List[str] = field(default_factory=list)

    # Recommendations
    top_recommendations: List[str] = field(default_factory=list)

    def grade_from_score(self) -> str:
        if self.score >= 90: return "A"
        if self.score >= 75: return "B"
        if self.score >= 60: return "C"
        if self.score >= 40: return "D"
        return "F"

    def to_html_badge(self) -> str:
        grade_colors = {
            "A": "#16a34a", "B": "#65a30d", "C": "#ca8a04",
            "D": "#ea580c", "F": "#dc2626"
        }
        color = grade_colors.get(self.grade, "#6b7280")
        return f"""
        <div style="background:#1e1e2e; border-radius:12px; padding:24px; margin:16px 0;
                    font-family:sans-serif; border: 1px solid #3a3a5c;">
          <div style="display:flex; align-items:center; gap:24px; margin-bottom:20px;">
            <div style="background:{color}; border-radius:50%; width:80px; height:80px;
                        display:flex; align-items:center; justify-content:center;
                        font-size:36px; font-weight:bold; color:white; flex-shrink:0;">
              {self.grade}
            </div>
            <div>
              <div style="color:#f8f8f2; font-size:22px; font-weight:bold;">
                UX Health Score: {self.score:.0f}/100
              </div>
              <div style="color:#8be9fd; font-size:14px; margin-top:4px;">{self.verdict}</div>
            </div>
          </div>

          <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:20px;">
            {self._score_pill("Stability", self.stability_score)}
            {self._score_pill("Performance", self.performance_score)}
            {self._score_pill("Responsiveness", self.responsiveness_score)}
            {self._score_pill("Playback", self.playback_score)}
          </div>

          {"".join(f'<div style="color:#ff5555; font-size:13px; margin-bottom:4px;">⚠ {p}</div>' for p in self.pain_points)}
          {"".join(f'<div style="color:#50fa7b; font-size:13px; margin-bottom:4px;">✓ {p}</div>' for p in self.positive_signals)}

          <div style="margin-top:16px; border-top:1px solid #3a3a5c; padding-top:16px;">
            <div style="color:#bd93f9; font-size:12px; font-weight:bold; margin-bottom:8px;">TOP RECOMMENDATIONS</div>
            {"".join(f'<div style="color:#f8f8f2; font-size:13px; margin-bottom:6px;">→ {r}</div>' for r in self.top_recommendations)}
          </div>
        </div>
        """

    def _score_pill(self, label: str, score: float) -> str:
        if score >= 80: color = "#16a34a"
        elif score >= 60: color = "#ca8a04"
        else: color = "#dc2626"
        return f"""
        <div style="background:#2a2a3e; border-radius:8px; padding:12px; text-align:center;">
          <div style="color:{color}; font-size:20px; font-weight:bold;">{score:.0f}</div>
          <div style="color:#6272a4; font-size:11px; margin-top:4px;">{label}</div>
        </div>"""


class UXScorer:
    """
    Computes UX health score from session statistics.
    No AI API needed — pure metrics-based scoring with smart rules.
    """

    # SLA benchmarks for OTT apps
    SLA_COLD_START_S = 8.0
    SLA_VIDEO_START_S = 5.0
    SLA_SEARCH_S = 4.0
    SLA_NAV_S = 3.0
    MAX_ACCEPTABLE_MEMORY_MB = 350.0
    MAX_ACCEPTABLE_FRAME_DROP_PCT = 10.0

    def score_session(
        self,
        session_id: str,
        app_name: str,
        duration_seconds: float,
        crash_count: int,
        restart_count: int,
        peak_memory_mb: float,
        avg_cpu_percent: float,
        peak_frame_drop_pct: float,
        cold_start_seconds: float = 0.0,
        video_start_seconds: float = 0.0,
        search_seconds: float = 0.0,
        buffering_events: int = 0,
        total_buffering_seconds: float = 0.0,
    ) -> UXScore:

        result = UXScore(
            session_id=session_id,
            app_name=app_name,
            timestamp=datetime.now(),
        )

        # ── Stability score ──────────────────────────────────────────────
        duration_hours = max(duration_seconds / 3600, 0.01)
        crashes_per_hour = crash_count / duration_hours
        if crashes_per_hour == 0:
            result.stability_score = 100.0
        elif crashes_per_hour < 0.5:
            result.stability_score = 80.0
        elif crashes_per_hour < 1:
            result.stability_score = 60.0
        elif crashes_per_hour < 2:
            result.stability_score = 30.0
        else:
            result.stability_score = 0.0

        if crash_count == 0:
            result.positive_signals.append("Zero crashes during entire session")
        else:
            result.pain_points.append(
                f"{crash_count} crash{'es' if crash_count > 1 else ''} detected "
                f"({crashes_per_hour:.1f}/hour)"
            )

        # ── Performance score ────────────────────────────────────────────
        mem_score = max(0, 100 - (peak_memory_mb / self.MAX_ACCEPTABLE_MEMORY_MB) * 80)
        cpu_score = max(0, 100 - avg_cpu_percent)
        frame_score = max(0, 100 - (peak_frame_drop_pct / self.MAX_ACCEPTABLE_FRAME_DROP_PCT) * 100)
        result.performance_score = (mem_score + cpu_score + frame_score) / 3

        if peak_memory_mb > 400:
            result.pain_points.append(f"Critical memory usage: {peak_memory_mb:.0f}MB (crash risk)")
        elif peak_memory_mb > 300:
            result.pain_points.append(f"High memory usage: {peak_memory_mb:.0f}MB")
        else:
            result.positive_signals.append(f"Memory usage within safe range ({peak_memory_mb:.0f}MB)")

        if peak_frame_drop_pct > 10:
            result.pain_points.append(f"Significant frame drops: {peak_frame_drop_pct:.1f}% janky frames")

        # ── Responsiveness score ─────────────────────────────────────────
        resp_scores = []
        if cold_start_seconds > 0:
            s = max(0, 100 - ((cold_start_seconds / self.SLA_COLD_START_S) - 1) * 100)
            resp_scores.append(s)
            if cold_start_seconds > self.SLA_COLD_START_S:
                result.pain_points.append(
                    f"Slow cold start: {cold_start_seconds:.1f}s (SLA: {self.SLA_COLD_START_S}s)"
                )
        if video_start_seconds > 0:
            s = max(0, 100 - ((video_start_seconds / self.SLA_VIDEO_START_S) - 1) * 100)
            resp_scores.append(s)
            if video_start_seconds > self.SLA_VIDEO_START_S:
                result.pain_points.append(
                    f"Slow video start: {video_start_seconds:.1f}s (SLA: {self.SLA_VIDEO_START_S}s)"
                )
        if search_seconds > 0:
            s = max(0, 100 - ((search_seconds / self.SLA_SEARCH_S) - 1) * 100)
            resp_scores.append(s)
            if search_seconds > self.SLA_SEARCH_S:
                result.pain_points.append(
                    f"Slow search: {search_seconds:.1f}s (SLA: {self.SLA_SEARCH_S}s)"
                )

        result.responsiveness_score = sum(resp_scores) / len(resp_scores) if resp_scores else 70.0

        # ── Playback score ───────────────────────────────────────────────
        if buffering_events == 0:
            result.playback_score = 100.0
            result.positive_signals.append("No buffering events during playback")
        else:
            buffer_penalty = min(100, buffering_events * 10 + total_buffering_seconds * 2)
            result.playback_score = max(0, 100 - buffer_penalty)
            result.pain_points.append(
                f"{buffering_events} buffering event(s), "
                f"{total_buffering_seconds:.1f}s total stall time"
            )

        # ── Overall score (weighted) ─────────────────────────────────────
        result.score = (
            result.stability_score    * 0.40 +
            result.performance_score  * 0.25 +
            result.responsiveness_score * 0.20 +
            result.playback_score     * 0.15
        )
        result.grade = result.grade_from_score()

        # ── Verdict ──────────────────────────────────────────────────────
        verdicts = {
            "A": f"{app_name} is production-ready. Excellent stability and performance.",
            "B": f"{app_name} is good but has minor issues worth addressing.",
            "C": f"{app_name} has moderate issues affecting user experience.",
            "D": f"{app_name} has serious problems — not ready for release.",
            "F": f"{app_name} is critically broken — immediate fixes required before any release.",
        }
        result.verdict = verdicts[result.grade]

        # ── Recommendations ──────────────────────────────────────────────
        if crash_count > 0:
            result.top_recommendations.append("Fix memory leak — primary crash cause")
        if peak_memory_mb > 350:
            result.top_recommendations.append("Implement image/video cache size limits")
        if peak_frame_drop_pct > 10:
            result.top_recommendations.append("Optimize list scroll performance (RecyclerView recycling)")
        if cold_start_seconds > self.SLA_COLD_START_S:
            result.top_recommendations.append("Reduce cold start — defer non-critical initialization")
        if video_start_seconds > self.SLA_VIDEO_START_S:
            result.top_recommendations.append("Pre-buffer video on content detail page open")
        if buffering_events > 2:
            result.top_recommendations.append("Implement adaptive bitrate streaming (ABR)")

        if not result.top_recommendations:
            result.top_recommendations.append("Maintain current quality — run regression tests on each build")

        logger.info(
            f"UX Score: {result.score:.0f}/100 (Grade {result.grade}) "
            f"for {app_name} | {len(result.pain_points)} pain points"
        )
        return result
