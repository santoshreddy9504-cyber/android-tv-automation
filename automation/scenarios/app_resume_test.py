"""
TC010 — App Background & Resume
Tests that the app handles backgrounding and foregrounding correctly:
- Note current screen state
- Press HOME to background the app
- Wait 10 seconds
- Relaunch / bring app to foreground
- Verify app resumes to same screen (not crashed / restarted)
- Check no memory spike after resume
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult
from config import config


class AppResumeTest(BaseScenario):

    SCENARIO_ID   = "TC010"
    SCENARIO_NAME = "App Background & Resume"

    HOME_INDICATORS = ["Home", "Featured", "Trending", "Movies", "Live", "Series"]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")
        pkg = config.app.package_name

        # ── 1. Ensure on home screen ──────────────────────────────────────
        self.step(
            "App is on home screen before background test",
            action_fn=lambda: self._remote.home(),
            expected_fn=lambda: self._inspector.any_text_visible(self.HOME_INDICATORS) is not None,
            timeout=10,
        )

        # ── 2. Record baseline memory ─────────────────────────────────────
        mem_before, _ = self._adb.get_memory_usage(pkg)
        pid_before = self._adb.get_app_pid(pkg)
        self._log.info(f"  Before background — PID: {pid_before}  Memory: {mem_before:.0f}MB")

        # ── 3. Background the app (press HOME) ───────────────────────────
        self.step(
            "Press HOME to background the app",
            action_fn=lambda: self._remote.press("HOME", delay=1.5),
            expected_fn=lambda: self._is_backgrounded(pkg),
            timeout=8,
            screenshot=True,
        )

        # ── 4. Wait 10 seconds in background ─────────────────────────────
        self._log.info("  App backgrounded — waiting 10 seconds ...")
        self._wait(10)

        # Verify app process still alive while backgrounded
        pid_during = self._adb.get_app_pid(pkg)
        self._result.steps.append(StepResult(
            "App process survives while backgrounded (10s)",
            pid_during is not None,
            f"PID: {pid_during}" if pid_during else "Process died while backgrounded",
        ))

        # ── 5. Bring app back to foreground ──────────────────────────────
        passed, duration_ms = self.timed_step(
            "App resumes to foreground",
            action_fn=lambda: self._adb.shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LEANBACK_LAUNCHER "
                f"-n {pkg}/{config.app.launch_activity}"
            ),
            expected_fn=lambda: self._app_in_foreground(pkg),
            sla_ms=3000,
            timeout=12,
            screenshot=True,
        )

        # ── 6. App returns to same screen ─────────────────────────────────
        self.step(
            "Home screen visible after resume (no crash / cold restart)",
            lambda: None,
            expected_fn=lambda: self._inspector.any_text_visible(self.HOME_INDICATORS) is not None,
            timeout=8,
            screenshot=True,
        )

        # ── 7. No crash on resume ─────────────────────────────────────────
        pid_after = self._adb.get_app_pid(pkg)
        self._result.steps.append(StepResult(
            "App PID unchanged after resume (no crash/restart)",
            pid_after is not None and pid_after == pid_before,
            f"Before: {pid_before}  After: {pid_after}" + (
                " — SAME (good)" if pid_after == pid_before
                else " — DIFFERENT (app restarted)"
            ),
        ))

        # ── 8. Memory after resume ────────────────────────────────────────
        mem_after, _ = self._adb.get_memory_usage(pkg)
        mem_delta = mem_after - mem_before
        self._log.info(f"  After resume — Memory: {mem_after:.0f}MB (delta: {mem_delta:+.0f}MB)")
        self._result.steps.append(StepResult(
            f"Memory growth after resume acceptable ({mem_delta:+.0f}MB < 50MB)",
            mem_delta < 50,
            f"Before: {mem_before:.0f}MB  After: {mem_after:.0f}MB  Delta: {mem_delta:+.0f}MB",
        ))

        self._take_screenshot("app_resume_complete")
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _is_backgrounded(self, pkg: str) -> bool:
        """Check the app is NOT in the foreground."""
        try:
            out = self._adb.shell(
                "dumpsys activity activities | grep mResumedActivity"
            )
            return pkg not in out
        except Exception:
            return True   # Assume backgrounded

    def _app_in_foreground(self, pkg: str) -> bool:
        """Check the app IS in the foreground."""
        try:
            out = self._adb.shell(
                "dumpsys activity activities | grep mResumedActivity"
            )
            return pkg in out
        except Exception:
            return self._inspector.any_text_visible(self.HOME_INDICATORS) is not None
