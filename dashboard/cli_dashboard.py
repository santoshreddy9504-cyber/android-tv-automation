"""
CLI Dashboard — live terminal UI using the 'rich' library.
Displays real-time device metrics, recent issues, and session stats.
"""

import time
import logging
import threading
from datetime import datetime
from typing import Optional, List

from config import config
from models.events import IssueEvent, IssueSeverity, IssueCategory

logger = logging.getLogger(__name__)

# Lazy import rich so the system still works without it
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich import box
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

_SEVERITY_STYLE = {
    IssueSeverity.CRITICAL: "bold red",
    IssueSeverity.HIGH:     "yellow",
    IssueSeverity.MEDIUM:   "cyan",
    IssueSeverity.LOW:      "blue",
    IssueSeverity.INFO:     "dim",
}
_CATEGORY_STYLE = {
    IssueCategory.CRASH:       "bold red",
    IssueCategory.NETWORK:     "orange3",
    IssueCategory.PLAYBACK:    "magenta",
    IssueCategory.UI:          "cyan",
    IssueCategory.PERFORMANCE: "yellow",
    IssueCategory.SYSTEM:      "green",
}
_CATEGORY_ICON = {
    IssueCategory.CRASH:       "💥",
    IssueCategory.NETWORK:     "🌐",
    IssueCategory.PLAYBACK:    "▶️",
    IssueCategory.UI:          "🖥",
    IssueCategory.PERFORMANCE: "📊",
    IssueCategory.SYSTEM:      "⚙️",
}


class CLIDashboard:
    """
    Live-refreshing terminal dashboard.
    Subscribes to issue events and performance snapshots via callbacks.
    """

    def __init__(self, session):
        self._session = session
        self._stop = session.stop_event
        self._recent_events: List[IssueEvent] = []
        self._max_recent = 15
        self._lock = threading.Lock()
        self._console = Console() if _RICH_AVAILABLE else None

    def on_event(self, event: IssueEvent):
        """Called by session to notify of new issue events."""
        with self._lock:
            self._recent_events.append(event)
            if len(self._recent_events) > self._max_recent:
                self._recent_events.pop(0)

    def run(self):
        """Entry point — runs in its own thread."""
        if not _RICH_AVAILABLE or not config.dashboard.cli_dashboard_enabled:
            logger.info("Rich not available or dashboard disabled; skipping CLI dashboard.")
            return

        logger.debug("CLI dashboard starting ...")
        interval = config.dashboard.cli_refresh_interval

        try:
            with Live(
                self._build_layout(),
                console=self._console,
                refresh_per_second=1 / interval,
                screen=True,
            ) as live:
                while not self._stop.is_set():
                    live.update(self._build_layout())
                    time.sleep(interval)
        except Exception as exc:
            logger.debug(f"Dashboard error: {exc}")

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(self._build_header(), size=3),
            Layout(name="body"),
            Layout(self._build_footer(), size=3),
        )
        layout["body"].split_row(
            Layout(self._build_stats_panel(), ratio=1),
            Layout(self._build_events_panel(), ratio=2),
        )
        return layout

    def _build_header(self) -> Panel:
        stats = self._session.stats
        elapsed = stats.duration_seconds
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)

        text = Text()
        text.append("  📺 Android TV Automation Monitor  ", style="bold white on blue")
        text.append(f"  Session: {stats.session_id}  ", style="dim")
        text.append(f"  Elapsed: {h:02d}:{m:02d}:{s:02d}  ", style="cyan")
        text.append(f"  App: {config.app.package_name}  ", style="green")
        return Panel(text, style="blue", padding=(0, 1))

    def _build_stats_panel(self) -> Panel:
        stats = self._session.stats
        perf = self._session.get_latest_performance()

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("metric", style="dim", width=20)
        table.add_column("value", style="bold white")

        # Session metrics
        table.add_row("Total Issues", str(stats.total_issues))
        table.add_row("Crashes", f"[bold red]{stats.crash_count}[/]")
        table.add_row("Auto Restarts", str(stats.restart_count))
        table.add_row("", "")

        # Category breakdown
        for cat, count in stats.issues_by_category.items():
            style = _CATEGORY_STYLE.get(IssueCategory(cat), "white")
            icon = _CATEGORY_ICON.get(IssueCategory(cat), "•")
            table.add_row(
                f"{icon} {cat}",
                f"[{style}]{count}[/]",
            )

        table.add_row("", "")

        # Performance
        if perf:
            cpu_style = "red" if perf.cpu_percent > config.monitor.cpu_alert_threshold else "green"
            mem_style = (
                "red"
                if perf.memory_mb > config.monitor.memory_alert_threshold_mb
                else "green"
            )
            table.add_row("CPU", f"[{cpu_style}]{perf.cpu_percent:.1f}%[/]")
            table.add_row(
                "Memory",
                f"[{mem_style}]{perf.memory_mb:.0f} MB[/]",
            )
            if perf.total_frames > 0:
                table.add_row(
                    "Frame Drops",
                    f"{perf.frame_drop_percent:.1f}% ({perf.janky_frames}/{perf.total_frames})",
                )
        else:
            table.add_row("CPU", "—")
            table.add_row("Memory", "—")

        table.add_row("", "")
        table.add_row("Avg CPU", f"{stats.avg_cpu:.1f}%")
        table.add_row("Peak CPU", f"{stats.peak_cpu:.1f}%")
        table.add_row("Avg Mem (MB)", f"{stats.avg_memory_mb:.0f}")
        table.add_row("Peak Mem (MB)", f"{stats.peak_memory_mb:.0f}")

        return Panel(
            table,
            title="[bold cyan]Session Stats[/]",
            border_style="cyan",
        )

    def _build_events_panel(self) -> Panel:
        with self._lock:
            events = list(self._recent_events)

        table = Table(
            box=box.SIMPLE_HEAD,
            expand=True,
            show_lines=False,
        )
        table.add_column("Time", style="dim", width=10, no_wrap=True)
        table.add_column("Cat", width=12, no_wrap=True)
        table.add_column("Sev", width=10, no_wrap=True)
        table.add_column("Title", style="bold")
        table.add_column("Message")

        for evt in reversed(events):
            cat_style = _CATEGORY_STYLE.get(evt.category, "white")
            sev_style = _SEVERITY_STYLE.get(evt.severity, "white")
            icon = _CATEGORY_ICON.get(evt.category, "")

            table.add_row(
                evt.timestamp.strftime("%H:%M:%S"),
                f"[{cat_style}]{icon} {evt.category.value}[/]",
                f"[{sev_style}]{evt.severity.value}[/]",
                evt.title[:30],
                evt.message[:80],
            )

        if not events:
            table.add_row(
                "", "", "", "[dim]No issues detected yet ...[/]", ""
            )

        return Panel(
            table,
            title=f"[bold yellow]Recent Issues (last {self._max_recent})[/]",
            border_style="yellow",
        )

    def _build_footer(self) -> Panel:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = Text()
        text.append(f"  Updated: {now}  ", style="dim")
        text.append("  Press Ctrl+C to stop session  ", style="bold yellow")
        return Panel(text, style="dim", padding=(0, 1))
