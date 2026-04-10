"""
Alert Handler — prints colour-coded alerts to the terminal.
"""

import logging
from datetime import datetime

from config import config
from models.events import IssueEvent, IssueSeverity, IssueCategory

logger = logging.getLogger(__name__)

# ANSI colour codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BLUE = "\033[94m"
_GREEN = "\033[92m"
_MAGENTA = "\033[95m"
_DIM = "\033[2m"

_SEVERITY_COLOR = {
    IssueSeverity.CRITICAL: _RED,
    IssueSeverity.HIGH:     _YELLOW,
    IssueSeverity.MEDIUM:   _CYAN,
    IssueSeverity.LOW:      _BLUE,
    IssueSeverity.INFO:     _DIM,
}

_CATEGORY_ICON = {
    IssueCategory.CRASH:       "💥",
    IssueCategory.NETWORK:     "🌐",
    IssueCategory.PLAYBACK:    "▶️ ",
    IssueCategory.UI:          "🖥 ",
    IssueCategory.PERFORMANCE: "📊",
    IssueCategory.SYSTEM:      "⚙️ ",
}


class AlertHandler:
    """Prints formatted, colour-coded issue alerts to stdout."""

    def handle(self, event: IssueEvent, adb=None):
        if not config.alert.print_alerts:
            return
        self._print_alert(event)

    def _print_alert(self, event: IssueEvent):
        use_color = config.alert.use_colors
        color = _SEVERITY_COLOR.get(event.severity, "") if use_color else ""
        reset = _RESET if use_color else ""
        bold = _BOLD if use_color else ""
        icon = _CATEGORY_ICON.get(event.category, "•")

        ts = event.timestamp.strftime("%H:%M:%S")
        separator = "─" * 70

        lines = [
            f"\n{color}{bold}{separator}{reset}",
            (
                f"{color}{bold}  {icon}  [{ts}] "
                f"[{event.severity.value}] [{event.category.value}]{reset}"
            ),
            f"{color}{bold}  {event.title}{reset}",
            f"  {event.message[:200]}",
        ]

        if event.screenshot_path:
            lines.append(f"  📸 Screenshot: {event.screenshot_path}")
        if event.log_path:
            lines.append(f"  📄 Logs saved: {event.log_path}")

        lines.append(f"{color}{separator}{reset}\n")

        print("\n".join(lines), flush=True)
