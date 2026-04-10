"""
TC004 — App Stability & Performance Test
Stress-navigates the app for several minutes and checks:
- No crashes
- Memory doesn't grow unbounded
- CPU stays reasonable
- Frame rate is acceptable
"""

import time
import random
from automation.scenarios.base_scenario import BaseScenario
from config import config


class StabilityTest(BaseScenario):

    SCENARIO_ID   = "TC004"
    SCENARIO_NAME = "App Stability & Performance Under Use"

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")
        pkg = config.app.package_name

        # Baseline CPU + memory
        cpu0 = self._adb.get_cpu_usage(pkg)
        mem0, _ = self._adb.get_memory_usage(pkg)
        self._log.info(f"  Baseline — CPU: {cpu0:.1f}%  Memory: {mem0:.0f}MB")

        # Rapid navigation stress — 60 seconds
        self._log.info("  Running 60s navigation stress ...")
        actions = [
            lambda: self._remote.right(),
            lambda: self._remote.left(),
            lambda: self._remote.down(),
            lambda: self._remote.up(),
            lambda: self._remote.select(),
            lambda: self._remote.back(),
        ]

        crashes_before = self._crash_count()
        start_time = time.time()

        while time.time() - start_time < 60:
            action = random.choice(actions)
            try:
                action()
            except Exception:
                pass
            time.sleep(0.3)

            # Check app is still alive every 10s
            if int(time.time() - start_time) % 10 == 0:
                if not self._adb.get_app_pid(pkg):
                    self._log.error("  App process died during stress!")
                    break

        crashes_after = self._crash_count()

        # Step — No crash during stress
        self.step(
            "No crash during 60s navigation stress",
            lambda: None,
            expected_fn=lambda: crashes_after == crashes_before,
        )

        # Post-stress CPU + memory
        cpu1 = self._adb.get_cpu_usage(pkg)
        mem1, _ = self._adb.get_memory_usage(pkg)
        self._log.info(f"  Post-stress — CPU: {cpu1:.1f}%  Memory: {mem1:.0f}MB")

        # Step — CPU under threshold
        self.step(
            f"CPU usage acceptable after stress ({cpu1:.1f}% < {config.monitor.cpu_alert_threshold}%)",
            lambda: None,
            expected_fn=lambda: cpu1 < config.monitor.cpu_alert_threshold,
        )

        # Step — Memory growth under 100MB
        mem_growth = mem1 - mem0
        self.step(
            f"Memory growth acceptable ({mem_growth:.0f}MB < 100MB)",
            lambda: None,
            expected_fn=lambda: mem_growth < 100,
        )

        # Frame drop check
        gfx = self._adb.get_gfxinfo(pkg)
        frame_drop_pct = gfx.get("frame_drop_pct", 0)
        self.step(
            f"Frame drops acceptable ({frame_drop_pct:.1f}% < 15%)",
            lambda: None,
            expected_fn=lambda: frame_drop_pct < 15,
        )

        self._take_screenshot("stability_complete")
        self._result.finish()
        return self._result

    def _crash_count(self) -> int:
        try:
            out = self._adb.shell(
                "dumpsys dropbox --print | grep -c CRASH 2>/dev/null || echo 0"
            )
            return int(out.strip().split("\n")[-1])
        except Exception:
            return 0
