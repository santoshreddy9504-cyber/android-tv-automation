"""
TC011 — Live TV / Live Channels
Tests the Live TV section:
- Navigate to Live / Live TV section
- Verify channel list loads
- Select a channel and verify stream starts within SLA
- Check stream stability (no buffering storms)
- Verify channel info / EPG overlay visible
- Test channel up/down navigation
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class LiveTVTest(BaseScenario):

    SCENARIO_ID   = "TC011"
    SCENARIO_NAME = "Live TV / Channels"

    LIVE_NAV = ["Live", "Live TV", "Live Channels", "TV", "Channels", "LIVE"]
    LIVE_INDICATORS  = ["Live", "LIVE", "On Air", "Now Playing", "Channel",
                         "EPG", "Programme", "Schedule"]
    PLAYER_INDICATORS = ["LIVE", "Live", "pause", "Pause", "00:", "HD", "4K"]
    CHANNEL_LIST_HINTS = ["Channel", "Ch.", "TV", "News", "Sports",
                           "Entertainment", "Movies"]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Navigate to Live section ───────────────────────────────────
        reached = self.step(
            "Navigate to Live TV section",
            action_fn=lambda: self._go_to_live(),
            expected_fn=lambda: self._on_live_screen(),
            timeout=15,
            screenshot=True,
        )

        if not reached:
            self._log.warning("  Live TV section not found — app may not have live content")
            self._result.steps.append(StepResult(
                "Live TV section availability",
                False,
                "Live / Live TV tab not found in navigation",
            ))
            self._result.finish()
            return self._result

        # ── 2. Channel list loads ─────────────────────────────────────────
        passed, load_ms = self.timed_step(
            "Live channel list loads",
            action_fn=lambda: None,
            expected_fn=lambda: self._has_channels(),
            sla_ms=5000,
            timeout=15,
            screenshot=True,
        )

        channel_count = self._inspector.get_content_count()
        self._result.steps.append(StepResult(
            f"Channel list has items ({channel_count} visible)",
            channel_count > 0,
            f"{channel_count} focusable items in channel list",
        ))
        self._log.info(f"  Channel count: {channel_count}")

        # ── 3. Select first channel — measure stream start ────────────────
        stream_started, start_ms = self.timed_step(
            "First channel stream starts (time to first frame)",
            action_fn=lambda: self._select_channel(),
            expected_fn=lambda: self._is_live_playing(),
            sla_ms=8000,    # Live streams allowed up to 8s
            timeout=20,
            screenshot=True,
        )

        if not stream_started:
            self._result.finish()
            return self._result

        # ── 4. Stream stable for 15 seconds ──────────────────────────────
        self._log.info("  Monitoring live stream for 15 seconds ...")
        stalls = self._monitor_stream(15)
        self.step(
            f"Live stream stable (stalls: {stalls})",
            lambda: None,
            expected_fn=lambda: stalls <= 1,
        )

        # ── 5. Channel info / EPG overlay ────────────────────────────────
        self.step(
            "Channel info / EPG overlay visible",
            action_fn=lambda: self._remote.select(),   # OK usually shows info
            expected_fn=lambda: self._inspector.any_text_visible(
                self.LIVE_INDICATORS) is not None,
            timeout=5,
            screenshot=True,
        )

        # ── 6. Next channel navigation ────────────────────────────────────
        self.step(
            "Navigate to next channel (channel up)",
            action_fn=lambda: self._channel_up(),
            expected_fn=lambda: self._is_live_playing(),
            timeout=12,
            screenshot=True,
        )

        # ── 7. Back to Live list ──────────────────────────────────────────
        self.step(
            "Back returns to channel list",
            action_fn=lambda: self._remote.back(2),
            expected_fn=lambda: self._on_live_screen(),
            timeout=8,
        )

        self._take_screenshot("live_tv_complete")
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _go_to_live(self):
        """Navigate via left sidebar — tap items until Live screen found."""
        self._go_to_app_root()
        self._wait(0.5)
        self._remote.left(1, delay=0.5)
        self._wait(0.4)
        self._ensure_in_app()
        for _ in range(12):
            focused = self._inspector.get_focused_element()
            if focused and any(s.lower() in focused.label.lower()
                               for s in self.LIVE_NAV):
                self._remote.select()
                self._wait(2)
                return
            if self._inspector.any_text_visible(self.LIVE_NAV):
                self._remote.select()
                self._wait(2)
                return
            self._remote.right(delay=0.35)

    def _on_live_screen(self) -> bool:
        return self._inspector.any_text_visible(
            self.LIVE_NAV + self.LIVE_INDICATORS + self.CHANNEL_LIST_HINTS
        ) is not None

    def _has_channels(self) -> bool:
        if self._inspector.any_text_visible(self.CHANNEL_LIST_HINTS):
            return True
        return self._inspector.get_content_count() > 2

    def _select_channel(self):
        """Navigate to and select the first channel."""
        self._remote.down(delay=0.4)
        self._wait(0.3)
        self._remote.select()
        self._wait(3)

    def _is_live_playing(self) -> bool:
        try:
            out = self._adb.shell("dumpsys media_session | grep -E 'state=3'")
            if "state=3" in out:
                return True
        except Exception:
            pass
        return self._inspector.any_text_visible(self.PLAYER_INDICATORS) is not None

    def _monitor_stream(self, duration_s: int) -> int:
        stalls = 0
        was_playing = True
        for _ in range(duration_s // 3):
            self._wait(3)
            playing = self._is_live_playing()
            if was_playing and not playing:
                stalls += 1
                self._log.warning(f"  Live stream stall detected ({stalls})")
            was_playing = playing
        return stalls

    def _channel_up(self):
        """Navigate to next channel — try channel-up keycode or D-pad up."""
        self._remote.press_keycode(166, delay=0.5)   # KEYCODE_CHANNEL_UP
        self._wait(3)
        if not self._is_live_playing():
            # Fallback to D-pad
            self._remote.up(delay=0.4)
            self._remote.select()
            self._wait(3)
