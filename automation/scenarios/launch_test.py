"""
TC001 — App Launch Test
Verifies the app launches successfully and the home screen loads within SLA.
"""

import time
from automation.scenarios.base_scenario import BaseScenario
from config import config


class AppLaunchTest(BaseScenario):

    SCENARIO_ID   = "TC001"
    SCENARIO_NAME = "App Launch & Home Screen Load"

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        pkg = config.app.package_name
        act = config.app.launch_activity
        home_indicators = config.client.home_indicators

        # Step 1 — Force stop to ensure cold start
        self.step(
            "Force stop app for cold start",
            lambda: self._adb.shell(f"am force-stop {pkg}"),
        )
        self._wait(2)

        # Step 2 — Launch and measure cold start time
        self._adb.shell(f"am force-stop {pkg}")
        self._wait(2)

        passed, duration_ms = self.timed_step(
            "App cold start — home screen visible",
            action_fn=lambda: self._adb.shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LEANBACK_LAUNCHER "
                f"-n {pkg}/{act}"
            ),
            expected_fn=lambda: self._inspector.any_text_visible(home_indicators) is not None,
            sla_ms=8000,
            timeout=20,
            screenshot=True,
        )

        # Allow a moment for logcat-based TimingMonitor to capture Displayed log
        self._wait(2)

        # Step 3 — Verify no crash on startup
        self.step(
            "Verify app process is running",
            lambda: None,
            expected_fn=lambda: self._adb.get_app_pid(pkg) is not None,
            timeout=15,
        )

        # Step 4 — Capture what's visible
        visible = self._inspector.get_all_text()
        self._log.info(f"  Visible text on home: {visible[:10]}")

        self._result.finish()
        return self._result
