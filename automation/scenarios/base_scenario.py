"""
Base class for all automated test scenarios.
"""

import time
import logging
import uuid
from datetime import datetime
from typing import Optional

from automation.remote_control import RemoteControl
from automation.ui_inspector import UIInspector
from core.adb_client import ADBClient


class StepResult:
    def __init__(self, name: str, passed: bool, message: str = "",
                 duration_ms: float = 0, screenshot: str = ""):
        self.name        = name
        self.passed      = passed
        self.message     = message
        self.duration_ms = duration_ms
        self.screenshot  = screenshot
        self.timestamp   = datetime.now()

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "passed":      self.passed,
            "message":     self.message,
            "duration_ms": round(self.duration_ms, 1),
            "screenshot":  self.screenshot,
            "timestamp":   self.timestamp.isoformat(),
        }


class ScenarioResult:
    def __init__(self, scenario_id: str, name: str):
        self.scenario_id = scenario_id
        self.name        = name
        self.steps       = []
        self.started_at  = datetime.now()
        self.ended_at    = None
        self.status      = "PENDING"    # PASS / FAIL / SKIP / ERROR
        self.error       = ""

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def duration_ms(self) -> float:
        end = self.ended_at or datetime.now()
        return (end - self.started_at).total_seconds() * 1000

    @property
    def steps_passed(self) -> int:
        return sum(1 for s in self.steps if s.passed)

    @property
    def steps_failed(self) -> int:
        return sum(1 for s in self.steps if not s.passed)

    def finish(self):
        self.ended_at = datetime.now()
        if not self.steps:
            self.status = "SKIP"
        elif all(s.passed for s in self.steps):
            self.status = "PASS"
        else:
            self.status = "FAIL"

    def to_dict(self) -> dict:
        return {
            "scenario_id":   self.scenario_id,
            "name":          self.name,
            "status":        self.status,
            "duration_ms":   round(self.duration_ms, 1),
            "steps_passed":  self.steps_passed,
            "steps_failed":  self.steps_failed,
            "error":         self.error,
            "started_at":    self.started_at.isoformat(),
            "ended_at":      self.ended_at.isoformat() if self.ended_at else None,
            "steps":         [s.to_dict() for s in self.steps],
        }


class BaseScenario:
    """
    Abstract base for all test scenarios.
    Provides helper methods for navigation, verification, and timing.
    """

    SCENARIO_ID   = "TC000"
    SCENARIO_NAME = "Base Scenario"

    def __init__(self, adb: ADBClient, remote: RemoteControl,
                 inspector: UIInspector, screenshot_dir: str,
                 timing_monitor: Optional[object] = None):
        self._adb        = adb
        self._remote     = remote
        self._inspector  = inspector
        self._ss_dir     = screenshot_dir
        self._timing     = timing_monitor
        self._log        = logging.getLogger(self.__class__.__name__)
        self._result     = ScenarioResult(self.SCENARIO_ID, self.SCENARIO_NAME)

    @property
    def result(self) -> ScenarioResult:
        return self._result

    def run(self) -> ScenarioResult:
        """Override in subclasses."""
        raise NotImplementedError

    # ── Step helpers ─────────────────────────────────────────────────────

    def step(self, name: str, action_fn, expected_fn=None,
             timeout: int = 8, screenshot: bool = False) -> bool:
        """
        Execute one test step.
        action_fn   — callable that performs the action
        expected_fn — callable that returns True if step passed
        """
        self._log.info(f"  STEP: {name}")
        t0 = time.time()
        passed = False
        message = ""
        ss_path = ""

        try:
            action_fn()

            if expected_fn:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    if expected_fn():
                        passed = True
                        break
                    time.sleep(1)
                if not passed:
                    message = f"Condition not met within {timeout}s"
            else:
                passed = True

        except Exception as exc:
            message = str(exc)
            self._log.warning(f"    Step error: {exc}")

        duration_ms = (time.time() - t0) * 1000

        if screenshot or not passed:
            ss_path = self._take_screenshot(name)

        status = "PASS" if passed else "FAIL"
        self._log.info(f"    → {status} ({duration_ms:.0f}ms) {message}")

        step_result = StepResult(name, passed, message, duration_ms, ss_path)
        self._result.steps.append(step_result)
        return passed

    def timed_step(self, name: str, action_fn, expected_fn,
                   sla_ms: float = 4000, timeout: int = 15,
                   screenshot: bool = True) -> tuple:
        """
        Execute a step and measure how long the expected condition takes.
        Returns (passed: bool, duration_ms: float)
        """
        self._log.info(f"  TIMED STEP: {name} (SLA: {sla_ms}ms)")
        action_fn()
        t0 = time.time()
        passed = False
        ss_path = ""

        deadline = time.time() + timeout
        while time.time() < deadline:
            if expected_fn():
                passed = True
                break
            time.sleep(0.5)

        duration_ms = (time.time() - t0) * 1000

        if passed and duration_ms > sla_ms:
            status = "SLOW"
        elif passed:
            status = "PASS"
        else:
            status = "FAIL"
            duration_ms = timeout * 1000

        message = (
            f"{duration_ms:.0f}ms (SLA {sla_ms}ms)"
            if passed else f"Did not load within {timeout}s"
        )

        self._log.info(f"    → {status} ({message})")

        if screenshot:
            ss_path = self._take_screenshot(name)

        step_result = StepResult(
            f"{name} [{status}]", passed or status == "SLOW",
            message, duration_ms, ss_path
        )
        self._result.steps.append(step_result)
        return passed, duration_ms

    # ── Utility ──────────────────────────────────────────────────────────

    def _take_screenshot(self, label: str) -> str:
        import os
        from utils.helpers import safe_filename, timestamp_str
        fname = f"{timestamp_str()}_{self.SCENARIO_ID}_{safe_filename(label)}.png"
        path = os.path.join(self._ss_dir, fname)
        self._adb.capture_screenshot(path)
        return path

    def _wait(self, seconds: float):
        time.sleep(seconds)

    def _any_visible(self, texts: list) -> bool:
        return self._inspector.any_text_visible(texts) is not None

    def _is_visible(self, text: str) -> bool:
        return self._inspector.is_text_visible(text)

    def _ensure_in_app(self) -> bool:
        """If ROD TV left the foreground, relaunch it. Never use HOME keycode."""
        from config import config
        pkg = config.app.package_name
        if not self._adb.is_app_foreground(pkg):
            self._log.warning("  App left foreground — relaunching ROD TV")
            self._adb.shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LEANBACK_LAUNCHER "
                f"-n {pkg}/.MainActivity"
            )
            self._wait(5)
            return self._adb.is_app_foreground(pkg)
        return True

    def _go_to_app_root(self):
        """Return to ROD TV home content by pressing BACK — never use HOME keycode."""
        rod_home = ["Popular Collections", "Continue Watching", "COMING SOON",
                    "RODtv", "Rodtv"]
        for _ in range(8):
            if not self._adb.is_app_foreground("com.webnexs.rod_tv"):
                self._ensure_in_app()
                self._wait(3)
                return
            if self._inspector.any_text_visible(rod_home):
                # Press RIGHT to move focus into content area (away from sidebar)
                self._remote.right(delay=0.4)
                return
            self._remote.back(delay=0.6)
        self._ensure_in_app()
