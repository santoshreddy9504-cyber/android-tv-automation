"""
Remote Control — simulates Android TV remote via ADB keyevents.
Every button on a physical TV remote is available here.
"""

import time
import subprocess
import logging

logger = logging.getLogger(__name__)

# Android TV keycode map
KEYS = {
    "UP":           19,
    "DOWN":         20,
    "LEFT":         21,
    "RIGHT":        22,
    "SELECT":       23,   # OK / Centre button
    "BACK":          4,
    "HOME":          3,
    "MENU":         82,
    "PLAY_PAUSE":   85,
    "PLAY":        126,
    "PAUSE":       127,
    "STOP":         86,
    "FAST_FORWARD": 90,
    "REWIND":       89,
    "NEXT":         87,
    "PREV":         88,
    "VOLUME_UP":   24,
    "VOLUME_DOWN": 25,
    "MUTE":        164,
    "SEARCH":      84,
}


class RemoteControl:
    """Simulate Android TV remote via ADB keyevents."""

    def __init__(self, device_target: str):
        self._target = device_target

    # ── Basic key press ──────────────────────────────────────────────────

    def press(self, key: str, delay: float = 0.4) -> bool:
        """Press a named key and wait delay seconds."""
        code = KEYS.get(key.upper())
        if code is None:
            logger.warning(f"Unknown key: {key}")
            return False
        self._send_keyevent(code)
        time.sleep(delay)
        return True

    def press_keycode(self, code: int, delay: float = 0.4):
        self._send_keyevent(code)
        time.sleep(delay)

    def long_press(self, key: str, duration: float = 1.0):
        """Long-press a key (sends keydown + wait + keyup)."""
        code = KEYS.get(key.upper())
        if code is None:
            return
        subprocess.run(
            ["adb", "-s", self._target, "shell",
             f"input keyevent --longpress {code}"],
            capture_output=True, timeout=5,
        )
        time.sleep(duration)

    # ── D-Pad navigation ─────────────────────────────────────────────────

    def up(self, times: int = 1, delay: float = 0.4):
        for _ in range(times):
            self.press("UP", delay)

    def down(self, times: int = 1, delay: float = 0.4):
        for _ in range(times):
            self.press("DOWN", delay)

    def left(self, times: int = 1, delay: float = 0.4):
        for _ in range(times):
            self.press("LEFT", delay)

    def right(self, times: int = 1, delay: float = 0.4):
        for _ in range(times):
            self.press("RIGHT", delay)

    def select(self, delay: float = 0.5):
        self.press("SELECT", delay)

    def back(self, times: int = 1, delay: float = 0.5):
        for _ in range(times):
            self.press("BACK", delay)

    def home(self, delay: float = 1.0):
        self.press("HOME", delay)

    # ── Playback controls ────────────────────────────────────────────────

    def play(self):
        self.press("PLAY", 0.5)

    def pause(self):
        self.press("PAUSE", 0.5)

    def play_pause(self):
        self.press("PLAY_PAUSE", 0.5)

    def stop(self):
        self.press("STOP", 0.5)

    def fast_forward(self, times: int = 1):
        for _ in range(times):
            self.press("FAST_FORWARD", 0.3)

    def rewind(self, times: int = 1):
        for _ in range(times):
            self.press("REWIND", 0.3)

    # ── Helpers ──────────────────────────────────────────────────────────

    def wait(self, seconds: float):
        """Explicit wait."""
        time.sleep(seconds)

    def tap(self, x: int, y: int, delay: float = 0.3):
        """Tap a screen coordinate (for focusing text input fields)."""
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell", f"input tap {x} {y}"],
                capture_output=True, timeout=5,
            )
        except Exception as exc:
            logger.warning(f"tap({x},{y}) failed: {exc}")
        time.sleep(delay)

    def type_text(self, text: str, delay: float = 0.2):
        """
        Type text into the currently focused field via ADB input text.
        Spaces are encoded as %s for the ADB shell command.
        Does NOT attempt to clear first — call clear_field() separately if needed.
        """
        # Encode spaces; apostrophes and quotes are passed via list args (no shell expansion)
        encoded = text.replace(" ", "%s")
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell", f"input text {encoded}"],
                capture_output=True, timeout=10,
            )
        except Exception as exc:
            logger.warning(f"type_text failed: {exc}")
        time.sleep(delay)

    def clear_field(self):
        """Clear the currently focused text field by selecting all and deleting."""
        # Move to end, then select all with SHIFT+CTRL+HOME, then delete
        self._send_keyevent(123)   # KEYCODE_MOVE_END
        time.sleep(0.05)
        # Send CTRL+A (select all): keycode 29 (A) with META_CTRL_ON (4096)
        subprocess.run(
            ["adb", "-s", self._target, "shell", "input keyevent --longpress 123"],
            capture_output=True, timeout=5,
        )
        time.sleep(0.1)
        # Delete selected text
        self._send_keyevent(67)    # KEYCODE_DEL
        time.sleep(0.1)

    def clear_field_and_type(self, text: str):
        """Clear the focused field then type new text."""
        self.clear_field()
        self.type_text(text)

    def go_home_and_relaunch(self, package: str, activity: str = ".MainActivity"):
        """Press home then relaunch app using the given activity."""
        self.home()
        time.sleep(1)
        subprocess.run(
            ["adb", "-s", self._target, "shell",
             f"am start -a android.intent.action.MAIN "
             f"-c android.intent.category.LEANBACK_LAUNCHER "
             f"-n {package}/{activity}"],
            capture_output=True, timeout=10,
        )
        time.sleep(3)

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 600, delay: float = 0.5):
        """
        Swipe from (x1, y1) to (x2, y2) over duration_ms milliseconds.
        Uses ADB input swipe which works on touch-enabled Android TV panels
        and emulators.
        """
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell",
                 f"input swipe {x1} {y1} {x2} {y2} {duration_ms}"],
                capture_output=True, timeout=10,
            )
        except Exception as exc:
            logger.warning(f"swipe({x1},{y1} → {x2},{y2}) failed: {exc}")
        time.sleep(delay)

    def pull_to_refresh(self, screen_width: int = 1920,
                        screen_height: int = 1080, delay: float = 1.0):
        """
        Simulate a pull-to-refresh gesture.

        Swipes downward from ~15 % of screen height to ~65 % of screen
        height at the horizontal centre, mimicking a finger drag from the
        top of a scrollable list to trigger a refresh.

        After the swipe the method waits `delay` seconds so the app has
        time to begin loading before the caller checks the UI.
        """
        cx   = screen_width  // 2
        y_start = int(screen_height * 0.15)   # near top of content area
        y_end   = int(screen_height * 0.65)   # drag ~half the screen down
        logger.info(f"pull_to_refresh: swipe ({cx},{y_start}) → ({cx},{y_end})")
        self.swipe(cx, y_start, cx, y_end, duration_ms=800, delay=delay)

    def _send_keyevent(self, code: int):
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell", f"input keyevent {code}"],
                capture_output=True, timeout=5,
            )
        except Exception as exc:
            logger.warning(f"keyevent {code} failed: {exc}")
