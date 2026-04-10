"""
TC003 — Video Playback Test
Selects the first available content item, plays it, verifies:
- Video starts within SLA
- Audio/video is playing (not frozen)
- Playback controls respond
- Seeks work
- Back navigation returns to browse
"""

import time
from automation.scenarios.base_scenario import BaseScenario


class VideoPlaybackTest(BaseScenario):

    SCENARIO_ID   = "TC003"
    SCENARIO_NAME = "Video Playback & Controls"

    PLAY_INDICATORS = [
        "Watch Now", "Play", "Resume", "Watch", "Start",
    ]
    PLAYER_INDICATORS = [
        "pause", "Pause", "00:", "Live", "HD", "4K",
        "resume", "Resume",
    ]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # Navigate to content
        self.step(
            "Navigate to first content item",
            action_fn=lambda: self._navigate_to_content(),
            expected_fn=lambda: self._inspector.any_text_visible(self.PLAY_INDICATORS) is not None,
            timeout=10,
            screenshot=True,
        )

        # Step — Measure video start time
        passed, start_ms = self.timed_step(
            "Video starts playing (time to first frame)",
            action_fn=lambda: self._start_playback(),
            expected_fn=lambda: self._is_playing(),
            sla_ms=5000,
            timeout=20,
            screenshot=True,
        )

        if not passed:
            self._result.finish()
            return self._result

        # Watch for 15 seconds and check for stalls
        self._log.info("  Monitoring playback for 15 seconds ...")
        stalls = self._monitor_playback(duration_s=15)

        self.step(
            f"Playback stable (stalls detected: {stalls})",
            lambda: None,
            expected_fn=lambda: stalls == 0,
        )

        # Step — Pause
        self.step(
            "Pause playback",
            action_fn=lambda: self._remote.play_pause(),
            expected_fn=lambda: not self._is_media_playing(),
            timeout=5,
            screenshot=True,
        )
        self._wait(2)

        # Step — Resume
        self.step(
            "Resume playback",
            action_fn=lambda: self._remote.play_pause(),
            expected_fn=lambda: self._is_playing(),
            timeout=5,
            screenshot=True,
        )

        # Step — Fast forward
        self.step(
            "Fast forward 10 seconds",
            action_fn=lambda: self._remote.fast_forward(3),
            expected_fn=lambda: self._is_playing(),
            timeout=8,
        )

        # Step — Back to browse (one back exits player; safe_back cancels exit dialog)
        self.step(
            "Back button returns to browse screen",
            action_fn=lambda: self._safe_back(1),
            expected_fn=lambda: not self._inspector.is_player_visible(),
            timeout=8,
            screenshot=True,
        )

        self._result.finish()
        return self._result

    def _navigate_to_content(self):
        """Navigate down into content rows and select the first item."""
        self._go_to_app_root()
        self._wait(1)
        self._remote.down(2, delay=0.4)
        self._remote.right(delay=0.4)
        self._wait(0.5)

    def _start_playback(self):
        """Press SELECT to open content detail, then start playback."""
        self._remote.select()
        self._wait(2)
        # Look for a play button and press it
        if self._inspector.any_text_visible(self.PLAY_INDICATORS):
            self._remote.select()
        else:
            # Some apps auto-play on select
            self._remote.play()

    def _is_playing(self) -> bool:
        """Check if video is actively playing."""
        # Method 1: media session state
        if self._is_media_playing():
            return True
        # Method 2: player UI visible
        if self._inspector.is_player_visible():
            return True
        # Method 3: any player indicator text
        if self._inspector.any_text_visible(self.PLAYER_INDICATORS):
            return True
        return False

    def _is_media_playing(self) -> bool:
        """Check Android media session for active playback."""
        try:
            out = self._adb.shell(
                "dumpsys media_session | grep -E 'state=3|PlaybackState'"
            )
            return "state=3" in out
        except Exception:
            return False

    def _monitor_playback(self, duration_s: int = 15) -> int:
        """Watch playback for duration_s seconds. Returns number of stalls."""
        stalls = 0
        was_playing = True
        interval = 3

        for _ in range(duration_s // interval):
            self._wait(interval)
            playing = self._is_media_playing()
            if was_playing and not playing:
                stalls += 1
                self._log.warning(f"  Stall detected! (total: {stalls})")
            was_playing = playing

        return stalls
