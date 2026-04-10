"""
UI Inspector — dumps and parses the Android UI hierarchy via uiautomator.
Used by test scenarios to verify what's on screen without manual checking.
"""

import subprocess
import re
import time
import logging
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class UIElement:
    """Represents a single UI element from uiautomator dump."""

    def __init__(self, node: ET.Element):
        self.text          = node.get("text", "")
        self.content_desc  = node.get("content-desc", "")
        self.resource_id   = node.get("resource-id", "")
        self.class_name    = node.get("class", "")
        self.clickable     = node.get("clickable") == "true"
        self.focusable     = node.get("focusable") == "true"
        self.focused       = node.get("focused") == "true"
        self.selected      = node.get("selected") == "true"
        self.enabled       = node.get("enabled") == "true"
        self.scrollable    = node.get("scrollable") == "true"
        self.bounds_str    = node.get("bounds", "[0,0][0,0]")
        self.bounds        = self._parse_bounds(self.bounds_str)

    def _parse_bounds(self, s: str) -> Dict[str, int]:
        nums = re.findall(r"\d+", s)
        if len(nums) >= 4:
            return {
                "x1": int(nums[0]), "y1": int(nums[1]),
                "x2": int(nums[2]), "y2": int(nums[3]),
            }
        return {"x1": 0, "y1": 0, "x2": 0, "y2": 0}

    @property
    def center(self) -> tuple:
        b = self.bounds
        return (b["x1"] + b["x2"]) // 2, (b["y1"] + b["y2"]) // 2

    @property
    def label(self) -> str:
        return self.text or self.content_desc or self.resource_id or self.class_name

    def __repr__(self):
        return f"UIElement(text={self.text!r}, focused={self.focused}, clickable={self.clickable})"


class UIInspector:
    """
    Wraps `adb shell uiautomator dump` to inspect on-screen elements.
    """

    def __init__(self, device_target: str):
        self._target = device_target

    def dump(self, retries: int = 3) -> Optional[str]:
        """Return raw XML from uiautomator dump."""
        for attempt in range(retries):
            try:
                # Dump to device then pull
                subprocess.run(
                    ["adb", "-s", self._target, "shell",
                     "uiautomator dump /sdcard/ui_dump.xml"],
                    capture_output=True, timeout=15,
                )
                result = subprocess.run(
                    ["adb", "-s", self._target, "shell", "cat /sdcard/ui_dump.xml"],
                    capture_output=True, text=True, timeout=10,
                )
                xml = result.stdout.strip()
                if xml and "<hierarchy" in xml:
                    return xml
            except Exception as exc:
                logger.debug(f"UI dump attempt {attempt+1} failed: {exc}")
            time.sleep(1)
        return None

    def get_all_elements(self) -> List[UIElement]:
        """Return all UI elements on screen."""
        xml = self.dump()
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
            return [UIElement(n) for n in root.iter("node")]
        except ET.ParseError as exc:
            logger.warning(f"UI XML parse error: {exc}")
            return []

    def get_focused_element(self) -> Optional[UIElement]:
        """Return the currently focused element (TV cursor position)."""
        for el in self.get_all_elements():
            if el.focused:
                return el
        return None

    def get_all_text(self) -> List[str]:
        """Return all visible text strings on screen."""
        return [
            el.text for el in self.get_all_elements()
            if el.text and el.text.strip()
        ]

    def find_by_text(self, text: str, exact: bool = False) -> Optional[UIElement]:
        """Find element by text (case-insensitive partial match by default)."""
        for el in self.get_all_elements():
            if exact:
                if el.text == text or el.content_desc == text:
                    return el
            else:
                if (text.lower() in el.text.lower() or
                        text.lower() in el.content_desc.lower()):
                    return el
        return None

    def find_all_by_text(self, text: str) -> List[UIElement]:
        results = []
        for el in self.get_all_elements():
            if text.lower() in el.text.lower() or text.lower() in el.content_desc.lower():
                results.append(el)
        return results

    def is_text_visible(self, text: str) -> bool:
        return self.find_by_text(text) is not None

    def any_text_visible(self, texts: List[str]) -> Optional[str]:
        """Return the first text from the list that is visible on screen."""
        for t in texts:
            if self.is_text_visible(t):
                return t
        return None

    def wait_for_text(self, text: str, timeout: int = 10) -> bool:
        """Wait up to timeout seconds for text to appear on screen."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_text_visible(text):
                return True
            time.sleep(1.5)
        return False

    def wait_for_any_text(self, texts: List[str], timeout: int = 10) -> Optional[str]:
        """Wait for any of the given texts to appear. Returns matched text or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = self.any_text_visible(texts)
            if found:
                return found
            time.sleep(1.5)
        return None

    def get_content_count(self) -> int:
        """Count visible focusable / clickable items (content cards)."""
        return sum(
            1 for el in self.get_all_elements()
            if (el.focusable or el.clickable) and el.enabled
        )

    def is_player_visible(self) -> bool:
        """Detect if a video player is on screen."""
        texts = self.get_all_text()
        combined = " ".join(texts).lower()
        player_hints = [
            "surfaceview", "videoview", "exoplayer",
            "pause", "play", "00:", "live",
        ]
        for hint in player_hints:
            if hint in combined:
                return True

        # Check for SurfaceView class (video surface)
        for el in self.get_all_elements():
            if "SurfaceView" in el.class_name or "VideoView" in el.class_name:
                return True
        return False

    def find_by_class(self, class_name: str) -> List[UIElement]:
        """Return all elements whose class matches (partial, case-insensitive)."""
        cn_lower = class_name.lower()
        return [
            el for el in self.get_all_elements()
            if cn_lower in el.class_name.lower()
        ]

    def find_input_fields(self) -> List[UIElement]:
        """
        Return all text input fields on screen.
        Works for both native (EditText) and React Native (ReactEditText) fields.
        """
        return [
            el for el in self.get_all_elements()
            if any(cls in el.class_name for cls in
                   ["EditText", "TextInput", "ReactEditText"])
               or (el.clickable and el.focusable and
                   el.class_name in ("android.widget.EditText",
                                     "com.facebook.react.views.textinput.ReactEditText"))
        ]

    def find_by_resource_id(self, res_id: str) -> Optional[UIElement]:
        """Find element by exact or partial resource-id match."""
        for el in self.get_all_elements():
            if res_id in el.resource_id:
                return el
        return None

    def screenshot_has_video(self, adb_client) -> bool:
        """Check if dumpsys media_session shows active playback."""
        try:
            out = adb_client.shell("dumpsys media_session | grep -i state")
            return "state=3" in out or "PlaybackState {state=3" in out
        except Exception:
            return False
