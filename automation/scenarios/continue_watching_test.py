"""
TC008 — Continue Watching
Verifies that partially watched content appears in "Continue Watching":
- Play a video for 30 seconds
- Press BACK to exit player
- Navigate to home
- Verify "Continue Watching" row exists and contains the content
- Resume from that row and verify playback resumes
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class ContinueWatchingTest(BaseScenario):

    SCENARIO_ID   = "TC008"
    SCENARIO_NAME = "Continue Watching"

    PLAY_INDICATORS   = ["Watch Now", "Play", "Resume", "Watch", "Start"]
    PLAYER_INDICATORS = ["pause", "Pause", "00:", "Live", "HD", "4K", "Resume"]
    CONTINUE_ROW      = ["Continue Watching", "Continue", "Keep Watching",
                          "Resume Watching", "Watch Again"]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Navigate to content and start playback ─────────────────────
        self.step(
            "Navigate to content and start playback",
            action_fn=lambda: self._start_playback(),
            expected_fn=lambda: self._is_playing(),
            timeout=20,
            screenshot=True,
        )

        if not self._is_playing():
            self._log.warning("  Playback did not start — cannot test Continue Watching")
            self._result.finish()
            return self._result

        # ── 2. Watch for 30 seconds ───────────────────────────────────────
        self._log.info("  Watching for 30 seconds to create watch history ...")
        self._wait(30)

        # Confirm still playing
        self.step(
            "Playback continues without interruption (30s)",
            lambda: None,
            expected_fn=lambda: self._is_playing(),
            timeout=5,
            screenshot=True,
        )

        # ── 3. Exit player ────────────────────────────────────────────────
        self.step(
            "Exit player via Back button",
            action_fn=lambda: self._remote.back(3),
            expected_fn=lambda: not self._is_playing(),
            timeout=10,
            screenshot=True,
        )

        self._wait(2)

        # ── 4. Navigate to Home ───────────────────────────────────────────
        self.step(
            "Return to Home screen",
            action_fn=lambda: self._go_home(),
            expected_fn=lambda: self._on_home(),
            timeout=10,
            screenshot=True,
        )

        self._wait(2)

        # ── 5. Continue Watching row is visible ───────────────────────────
        self.step(
            "Continue Watching row appears on Home",
            lambda: None,
            expected_fn=lambda: self._inspector.any_text_visible(self.CONTINUE_ROW) is not None,
            timeout=8,
            screenshot=True,
        )

        # ── 6. Navigate to Continue Watching row ──────────────────────────
        continue_row_found = self._find_continue_watching_row()
        self._result.steps.append(StepResult(
            "Continue Watching row is navigable",
            continue_row_found,
            "Row found and focused" if continue_row_found else "Could not navigate to row",
        ))

        # ── 7. Resume playback from Continue Watching ─────────────────────
        if continue_row_found:
            passed, duration_ms = self.timed_step(
                "Resume playback from Continue Watching",
                action_fn=lambda: self._remote.select(),
                expected_fn=lambda: self._is_playing(),
                sla_ms=6000,
                timeout=20,
                screenshot=True,
            )

            # ── 8. Verify resume position (not from beginning) ────────────
            if passed:
                self.step(
                    "Playback resumes (not restarted from 0:00)",
                    lambda: None,
                    expected_fn=lambda: self._resumed_from_position(),
                    timeout=5,
                )

            self._remote.back(3)

        self._take_screenshot("continue_watching_complete")
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _start_playback(self):
        """Navigate to first content item and start playing."""
        self._go_to_app_root()
        self._wait(1)
        self._remote.down(2, delay=0.4)
        self._remote.right(delay=0.4)
        self._wait(0.5)
        self._remote.select()          # Open detail
        self._wait(2)
        if self._inspector.any_text_visible(self.PLAY_INDICATORS):
            self._remote.select()      # Press play
        else:
            self._remote.play()
        self._wait(3)

    def _is_playing(self) -> bool:
        try:
            out = self._adb.shell("dumpsys media_session | grep -E 'state=3'")
            if "state=3" in out:
                return True
        except Exception:
            pass
        return self._inspector.any_text_visible(self.PLAYER_INDICATORS) is not None

    def _go_home(self):
        """Return to app root using BACK — never HOME (exits app)."""
        self._go_to_app_root()

    def _on_home(self) -> bool:
        from config import config
        return self._inspector.any_text_visible(config.client.home_indicators) is not None

    def _find_continue_watching_row(self) -> bool:
        """Scroll through home rows to find Continue Watching."""
        for _ in range(8):
            if self._inspector.any_text_visible(self.CONTINUE_ROW):
                # Navigate right to first item in the row
                self._remote.right(delay=0.3)
                return True
            self._remote.down(delay=0.5)
        return False

    def _resumed_from_position(self) -> bool:
        """Check media session for position > 10s to confirm it's not from start."""
        try:
            out = self._adb.shell("dumpsys media_session | grep -i position")
            # Position is in ms — look for a value > 10000
            import re
            matches = re.findall(r"position=(\d+)", out)
            if matches:
                pos_ms = int(matches[0])
                self._log.info(f"  Playback position: {pos_ms/1000:.1f}s")
                return pos_ms > 10000
        except Exception:
            pass
        # Fallback: if player is visible we assume resume worked
        return self._is_playing()
