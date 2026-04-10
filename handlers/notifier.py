"""
Notifier — plays sound alerts and sends desktop notifications on critical events.
"""

import os
import sys
import logging
import subprocess
import threading
from datetime import datetime

from config import config
from models.events import IssueEvent, IssueSeverity, IssueCategory

logger = logging.getLogger(__name__)


class NotifierHandler:
    """
    Sends desktop notifications and plays audio alerts for critical issues.
    Supports macOS (osascript, afplay) and Linux (notify-send, paplay).
    """

    def __init__(self):
        self._platform = sys.platform
        self._sound_lock = threading.Lock()

    def handle(self, event: IssueEvent, adb=None):
        if config.alert.sound_alerts_enabled:
            self._maybe_play_sound(event)

        if config.alert.desktop_notifications:
            self._send_desktop_notification(event)

    # ------------------------------------------------------------------
    # Sound
    # ------------------------------------------------------------------

    def _maybe_play_sound(self, event: IssueEvent):
        should_beep = (
            (event.severity == IssueSeverity.CRITICAL and config.alert.sound_on_critical) or
            (event.category == IssueCategory.CRASH and config.alert.sound_on_crash)
        )
        if should_beep:
            threading.Thread(target=self._beep, daemon=True).start()

    def _beep(self):
        with self._sound_lock:
            try:
                if self._platform == "darwin":
                    # Play system alert sound on macOS
                    subprocess.run(
                        ["afplay", "/System/Library/Sounds/Sosumi.aiff"],
                        timeout=3, capture_output=True,
                    )
                elif self._platform.startswith("linux"):
                    # Try paplay (PulseAudio) then fallback to terminal bell
                    result = subprocess.run(
                        ["paplay", "/usr/share/sounds/alsa/Front_Left.wav"],
                        timeout=3, capture_output=True,
                    )
                    if result.returncode != 0:
                        print("\a", end="", flush=True)
                else:
                    print("\a", end="", flush=True)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                print("\a", end="", flush=True)
            except Exception as exc:
                logger.debug(f"Sound alert error: {exc}")

    # ------------------------------------------------------------------
    # Desktop notification
    # ------------------------------------------------------------------

    def _send_desktop_notification(self, event: IssueEvent):
        title = f"[{event.category.value}] {event.title}"
        body = event.message[:200]

        try:
            if self._platform == "darwin":
                script = (
                    f'display notification "{body}" '
                    f'with title "{title}" '
                    f'sound name "Submarine"'
                )
                subprocess.run(
                    ["osascript", "-e", script],
                    timeout=5, capture_output=True,
                )
            elif self._platform.startswith("linux"):
                urgency = (
                    "critical"
                    if event.severity == IssueSeverity.CRITICAL
                    else "normal"
                )
                subprocess.run(
                    [
                        "notify-send",
                        f"--urgency={urgency}",
                        "--expire-time=8000",
                        title, body,
                    ],
                    timeout=5, capture_output=True,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        except Exception as exc:
            logger.debug(f"Desktop notification error: {exc}")
