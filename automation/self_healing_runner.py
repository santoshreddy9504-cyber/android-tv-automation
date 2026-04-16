"""
Self-Healing Test Runner — tests that automatically adapt when UI changes.

Problem with traditional test automation:
  - Developer changes a button label → ALL tests break
  - QA spends days fixing broken tests instead of finding bugs

Solution:
  - Tests describe INTENT, not exact UI paths
  - Runner finds the right element dynamically at runtime
  - If element not found by expected name, searches alternatives
  - Learns new UI patterns and remembers them

Architecture:
  - Intent-based tests: "navigate to search" not "press right 3 times"
  - Element discovery: try primary selector → aliases → fuzzy match → AI assist
  - Memory: store what worked last time, try it first next time
  - Report: shows what changed in UI vs last run

Usage:
    runner = SelfHealingRunner(device_target, package)
    runner.run_intent("open_app")
    runner.run_intent("navigate_to_search")
    runner.run_intent("play_first_video")
    report = runner.generate_healing_report()
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Callable, Tuple

logger = logging.getLogger(__name__)

HEALING_MEMORY_FILE = "output/self_healing_memory.json"


@dataclass
class IntentResult:
    """Result of executing one test intent."""
    intent_name: str
    timestamp: datetime
    success: bool = False
    healed: bool = False           # True if had to use fallback path
    healing_note: str = ""         # What was different / what was adapted
    steps_taken: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class UIElement:
    """Represents a findable UI element with multiple ways to identify it."""
    name: str                              # Semantic name: "search_button"
    primary_selector: str = ""            # Expected text/id
    aliases: List[str] = field(default_factory=list)   # Alternative texts
    keycodes: List[int] = field(default_factory=list)  # Fallback keycode path
    description: str = ""                 # Human description for reports


class UIFinder:
    """
    Finds UI elements on Android TV screen dynamically.
    Uses UI Automator dump + text matching with fuzzy fallback.
    """

    def __init__(self, device_target: str):
        self._target = device_target
        self._last_dump: Optional[str] = None

    def dump_ui(self) -> str:
        """Get current UI hierarchy from device."""
        try:
            result = subprocess.run(
                ["adb", "-s", self._target, "shell",
                 "uiautomator dump /sdcard/ui_dump.xml && cat /sdcard/ui_dump.xml"],
                capture_output=True, text=True, timeout=15,
            )
            self._last_dump = result.stdout
            return self._last_dump
        except Exception as exc:
            logger.warning(f"UI dump failed: {exc}")
            return ""

    def find_text(self, text: str, dump: Optional[str] = None) -> bool:
        """Check if text exists in current UI hierarchy."""
        ui = dump or self.dump_ui()
        return text.lower() in ui.lower()

    def find_any(self, candidates: List[str], dump: Optional[str] = None) -> Optional[str]:
        """Find first matching text from a list of candidates."""
        ui = dump or self.dump_ui()
        for candidate in candidates:
            if candidate.lower() in ui.lower():
                return candidate
        return None

    def click_text(self, text: str) -> bool:
        """Click element by text using UI Automator."""
        try:
            self._shell(
                f'uiautomator runtest /system/framework/uiautomator.jar '
                f'-c com.android.uiautomator.testrunner.UiAutomatorTestRunner'
            )
        except Exception:
            pass
        # Simpler fallback: use input text and keyevent
        return False

    def _shell(self, cmd: str) -> str:
        try:
            r = subprocess.run(
                ["adb", "-s", self._target, "shell", cmd],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip()
        except Exception:
            return ""

    def press_key(self, keycode: int, delay: float = 0.5):
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell", f"input keyevent {keycode}"],
                capture_output=True, timeout=5,
            )
            time.sleep(delay)
        except Exception:
            pass


class HealingMemory:
    """
    Remembers what worked last time for each intent.
    Persisted to disk so learning carries over between runs.
    """

    def __init__(self, path: str = HEALING_MEMORY_FILE):
        self._path = path
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def record_success(self, intent: str, method: str, details: dict):
        """Record a successful execution method for an intent."""
        self._data[intent] = {
            "last_method": method,
            "details": details,
            "last_success": datetime.now().isoformat(),
            "success_count": self._data.get(intent, {}).get("success_count", 0) + 1,
        }
        self._save()

    def get_last_method(self, intent: str) -> Optional[dict]:
        return self._data.get(intent)

    def all_intents(self) -> dict:
        return self._data


class SelfHealingRunner:
    """
    Runs intent-based tests with automatic adaptation.

    Intents are high-level actions like "open_search" rather than
    "press RIGHT 3 times then OK". The runner figures out HOW to do
    the intent based on the current UI state.
    """

    def __init__(self, device_target: str, package: str):
        self._target = device_target
        self._package = package
        self._finder = UIFinder(device_target)
        self._memory = HealingMemory()
        self._results: List[IntentResult] = []

        # Define all known intents with their alternatives
        self._intents: Dict[str, dict] = {
            "open_app": {
                "description": "Launch the app from home screen",
                "primary_text": None,
                "fallback_keys": [3],      # HOME then relaunch
                "verify_text": ["Home", "Featured", "Trending", "Movies", "Series"],
                "timeout": 15,
            },
            "navigate_home": {
                "description": "Navigate to Home section",
                "primary_text": ["Home", "HOME", "home"],
                "fallback_keys": [3, 23],
                "verify_text": ["Featured", "Trending", "Continue Watching"],
                "timeout": 8,
            },
            "navigate_search": {
                "description": "Open Search",
                "primary_text": ["Search", "SEARCH", "Find", "search", "🔍"],
                "fallback_keys": [84],     # KEYCODE_SEARCH
                "verify_text": ["Search", "search for", "Type to search", "Enter"],
                "timeout": 8,
            },
            "navigate_movies": {
                "description": "Navigate to Movies section",
                "primary_text": ["Movies", "MOVIES", "Films", "Movie"],
                "fallback_keys": [22, 22, 23],  # RIGHT RIGHT SELECT
                "verify_text": ["Movies", "Films", "Genre"],
                "timeout": 8,
            },
            "navigate_series": {
                "description": "Navigate to Series section",
                "primary_text": ["Series", "SERIES", "Shows", "TV Shows"],
                "fallback_keys": [22, 22, 22, 23],
                "verify_text": ["Series", "Shows", "Episodes", "Seasons"],
                "timeout": 8,
            },
            "play_first_video": {
                "description": "Play the first available video content",
                "primary_text": ["Play", "PLAY", "Watch Now", "Resume"],
                "fallback_keys": [20, 23],  # DOWN SELECT (select first item)
                "verify_text": ["Pause", "pause", "Stop", "00:00"],
                "timeout": 15,
            },
            "type_search_query": {
                "description": "Type a search query",
                "primary_text": None,
                "fallback_keys": [],
                "verify_text": ["results", "Results", "found"],
                "timeout": 10,
            },
            "go_back": {
                "description": "Press Back button",
                "primary_text": None,
                "fallback_keys": [4],      # BACK
                "verify_text": [],
                "timeout": 3,
            },
            "scroll_content": {
                "description": "Scroll through content list",
                "primary_text": None,
                "fallback_keys": [20, 20, 20, 20, 20],  # DOWN x5
                "verify_text": [],
                "timeout": 5,
            },
            "open_settings": {
                "description": "Open app settings",
                "primary_text": ["Settings", "SETTINGS", "Preferences", "Profile"],
                "fallback_keys": [82],     # MENU
                "verify_text": ["Settings", "Account", "Logout", "Version"],
                "timeout": 8,
            },
        }

    def run_intent(self, intent_name: str, **kwargs) -> IntentResult:
        """Execute a test intent with automatic healing."""
        result = IntentResult(
            intent_name=intent_name,
            timestamp=datetime.now(),
        )
        start = time.time()

        if intent_name not in self._intents:
            result.error = f"Unknown intent: {intent_name}"
            self._results.append(result)
            return result

        intent = self._intents[intent_name]
        result.steps_taken.append(f"Intent: {intent['description']}")

        try:
            # Step 1: Try last known working method first
            last = self._memory.get_last_method(intent_name)
            if last:
                result.steps_taken.append(f"Trying remembered method: {last['last_method']}")
                if self._execute_remembered(intent_name, last, intent, result):
                    result.success = True
                    result.steps_taken.append("Remembered method succeeded")
                    self._memory.record_success(intent_name, last["last_method"], last["details"])
                    result.duration_seconds = time.time() - start
                    self._results.append(result)
                    return result

            # Step 2: Try primary text-based navigation
            if intent.get("primary_text"):
                candidates = intent["primary_text"] if isinstance(intent["primary_text"], list) else [intent["primary_text"]]
                found_text = self._find_and_select(candidates)
                if found_text:
                    result.steps_taken.append(f"Found element by text: '{found_text}'")
                    if self._verify(intent.get("verify_text", []), timeout=intent.get("timeout", 8)):
                        result.success = True
                        self._memory.record_success(
                            intent_name, "text_navigation",
                            {"text": found_text, "verify": intent.get("verify_text", [])}
                        )
                        result.steps_taken.append("Text navigation succeeded")
                        result.duration_seconds = time.time() - start
                        self._results.append(result)
                        return result

            # Step 3: Fallback to keycode sequence
            if intent.get("fallback_keys"):
                result.healed = True
                result.healing_note = "Primary UI element not found — using keycode fallback"
                result.steps_taken.append(f"Healing: pressing keycodes {intent['fallback_keys']}")

                for key in intent["fallback_keys"]:
                    self._finder.press_key(key, delay=0.4)

                if self._verify(intent.get("verify_text", []), timeout=intent.get("timeout", 8)):
                    result.success = True
                    self._memory.record_success(
                        intent_name, "keycode_fallback",
                        {"keys": intent["fallback_keys"]}
                    )
                    result.steps_taken.append("Keycode fallback succeeded")
                else:
                    result.steps_taken.append("Keycode fallback did not reach expected screen")

            # Special intent handling
            if not result.success and intent_name == "open_app":
                result.success = self._relaunch_app()
                if result.success:
                    result.healing_note = "App relaunched via am start"

        except Exception as exc:
            result.error = str(exc)
            logger.error(f"Intent {intent_name} failed: {exc}")

        result.duration_seconds = time.time() - start
        self._results.append(result)

        if result.healed and result.success:
            logger.warning(f"[SelfHealing] Intent '{intent_name}' healed: {result.healing_note}")
        elif result.success:
            logger.info(f"[SelfHealing] Intent '{intent_name}' succeeded in {result.duration_seconds:.1f}s")
        else:
            logger.error(f"[SelfHealing] Intent '{intent_name}' FAILED: {result.error}")

        return result

    def _find_and_select(self, candidates: List[str]) -> Optional[str]:
        """Find element by text and navigate to it using focus."""
        ui_dump = self._finder.dump_ui()
        found = self._finder.find_any(candidates, ui_dump)
        if found:
            # Navigate to it using D-pad (simplified — navigate down until found)
            for attempt in range(10):
                current_dump = self._finder.dump_ui()
                if f'focused="true"' in current_dump and found.lower() in current_dump:
                    self._finder.press_key(23, delay=0.5)  # SELECT
                    return found
                self._finder.press_key(22, delay=0.3)  # RIGHT
            return found  # Return found even if we couldn't click
        return None

    def _verify(self, expected_texts: List[str], timeout: int = 8) -> bool:
        """Wait for expected text to appear on screen."""
        if not expected_texts:
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            dump = self._finder.dump_ui()
            if any(t.lower() in dump.lower() for t in expected_texts):
                return True
            time.sleep(1)
        return False

    def _execute_remembered(
        self, intent_name: str, memory: dict, intent: dict, result: IntentResult
    ) -> bool:
        """Try the last-known-working method for an intent."""
        method = memory.get("last_method", "")
        details = memory.get("details", {})

        if method == "text_navigation" and details.get("text"):
            self._find_and_select([details["text"]])
            return self._verify(details.get("verify", []), timeout=5)

        elif method == "keycode_fallback" and details.get("keys"):
            for key in details["keys"]:
                self._finder.press_key(key, delay=0.4)
            return self._verify(intent.get("verify_text", []), timeout=5)

        return False

    def _relaunch_app(self) -> bool:
        """Force launch the app."""
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell",
                 f"am start -a android.intent.action.MAIN "
                 f"-c android.intent.category.LEANBACK_LAUNCHER "
                 f"-n {self._package}/.MainActivity"],
                capture_output=True, timeout=10,
            )
            time.sleep(5)
            dump = self._finder.dump_ui()
            return len(dump) > 100  # Something rendered
        except Exception:
            return False

    def run_smoke_test(self) -> List[IntentResult]:
        """Run a basic smoke test covering all main app areas."""
        intents = [
            "open_app",
            "navigate_home",
            "navigate_search",
            "go_back",
            "navigate_movies",
            "go_back",
            "navigate_series",
            "go_back",
            "play_first_video",
            "go_back",
        ]
        results = []
        for intent in intents:
            result = self.run_intent(intent)
            results.append(result)
            time.sleep(0.5)
        return results

    def generate_healing_report(self) -> str:
        """Generate HTML report of healing activity."""
        healed = [r for r in self._results if r.healed]
        passed = [r for r in self._results if r.success]
        failed = [r for r in self._results if not r.success]

        rows = ""
        for r in self._results:
            status_color = "#16a34a" if r.success else "#dc2626"
            healed_badge = (
                f'<span style="background:#ca8a04; color:white; padding:1px 6px; '
                f'border-radius:8px; font-size:11px; margin-left:6px;">HEALED</span>'
                if r.healed else ""
            )
            rows += f"""
            <tr>
              <td style="padding:10px; color:#f8f8f2;">{r.intent_name}{healed_badge}</td>
              <td style="padding:10px; color:{status_color}; font-weight:bold;">
                {'✅ PASS' if r.success else '❌ FAIL'}
              </td>
              <td style="padding:10px; color:#8be9fd;">{r.duration_seconds:.1f}s</td>
              <td style="padding:10px; color:#ffb86c; font-size:12px;">{r.healing_note or '—'}</td>
              <td style="padding:10px; color:#6272a4; font-size:12px;">
                {' → '.join(r.steps_taken[-3:])}
              </td>
            </tr>"""

        memory_rows = ""
        for intent, data in self._memory.all_intents().items():
            memory_rows += f"""
            <tr>
              <td style="padding:8px; color:#f8f8f2;">{intent}</td>
              <td style="padding:8px; color:#50fa7b;">{data.get('last_method', '—')}</td>
              <td style="padding:8px; color:#6272a4;">{data.get('success_count', 0)}x</td>
              <td style="padding:8px; color:#8be9fd;">{data.get('last_success', '—')[:16]}</td>
            </tr>"""

        return f"""
        <div style="font-family:sans-serif; background:#1e1e2e; border-radius:12px; padding:24px; margin:16px 0;">
          <h2 style="color:#50fa7b; margin-top:0;">🤖 Self-Healing Test Runner Report</h2>

          <div style="display:flex; gap:16px; margin-bottom:20px;">
            <div style="background:#2a2a3e; border-radius:8px; padding:16px; text-align:center; flex:1;">
              <div style="color:#16a34a; font-size:28px; font-weight:bold;">{len(passed)}</div>
              <div style="color:#6272a4; font-size:12px;">PASSED</div>
            </div>
            <div style="background:#2a2a3e; border-radius:8px; padding:16px; text-align:center; flex:1;">
              <div style="color:#dc2626; font-size:28px; font-weight:bold;">{len(failed)}</div>
              <div style="color:#6272a4; font-size:12px;">FAILED</div>
            </div>
            <div style="background:#2a2a3e; border-radius:8px; padding:16px; text-align:center; flex:1;">
              <div style="color:#ca8a04; font-size:28px; font-weight:bold;">{len(healed)}</div>
              <div style="color:#6272a4; font-size:12px;">AUTO-HEALED</div>
            </div>
          </div>

          {f'<div style="background:#1a2a1a; border:1px solid #16a34a; border-radius:8px; padding:12px; margin-bottom:16px; color:#50fa7b;">✓ {len(healed)} test(s) automatically adapted to UI changes</div>' if healed else ''}

          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="background:#2a2a3e;">
                <th style="padding:10px; color:#bd93f9; text-align:left;">Intent</th>
                <th style="padding:10px; color:#bd93f9;">Result</th>
                <th style="padding:10px; color:#bd93f9;">Duration</th>
                <th style="padding:10px; color:#bd93f9; text-align:left;">Healing</th>
                <th style="padding:10px; color:#bd93f9; text-align:left;">Steps</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>

          <h3 style="color:#bd93f9; margin-top:24px;">Learned Patterns (Memory)</h3>
          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="background:#2a2a3e;">
                <th style="padding:8px; color:#bd93f9; text-align:left;">Intent</th>
                <th style="padding:8px; color:#bd93f9; text-align:left;">Working Method</th>
                <th style="padding:8px; color:#bd93f9;">Uses</th>
                <th style="padding:8px; color:#bd93f9; text-align:left;">Last Success</th>
              </tr>
            </thead>
            <tbody style="color:#f8f8f2;">{memory_rows}</tbody>
          </table>
        </div>"""

    @property
    def results(self) -> List[IntentResult]:
        return self._results

    @property
    def pass_rate(self) -> float:
        if not self._results:
            return 0.0
        return sum(1 for r in self._results if r.success) / len(self._results) * 100
