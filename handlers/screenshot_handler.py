"""
Screenshot Handler — captures and saves device screenshots on issue events.
"""

import os
import logging
from datetime import datetime

from config import config, SCREENSHOTS_DIR
from models.events import IssueEvent, IssueSeverity

logger = logging.getLogger(__name__)


class ScreenshotHandler:
    """
    Captures a screenshot from the device when an issue event is received.
    Screenshots are named with timestamp + category + severity.
    """

    def __init__(self):
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    def handle(self, event: IssueEvent, adb=None):
        if not config.alert.capture_screenshot_on_issue:
            return

        # Only capture for configured severity levels
        if event.severity.value not in config.alert.screenshot_on_severities:
            return

        if adb is None:
            return

        path = self._build_path(event)
        try:
            success = adb.capture_screenshot(path)
            if success:
                event.screenshot_path = path
                logger.info(f"Screenshot saved: {path}")
            else:
                logger.warning(f"Screenshot capture failed for event: {event.title}")
        except Exception as exc:
            logger.error(f"Screenshot handler error: {exc}")

    def _build_path(self, event: IssueEvent) -> str:
        ts = event.timestamp.strftime("%Y%m%d_%H%M%S")
        cat = event.category.value.lower()
        sev = event.severity.value.lower()
        # Sanitise title for filename
        title = event.title.replace(" ", "_").replace("/", "-")[:40]
        filename = f"{ts}_{cat}_{sev}_{title}.png"
        return os.path.join(SCREENSHOTS_DIR, filename)
