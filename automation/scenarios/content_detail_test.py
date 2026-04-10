"""
TC006 — Content Detail Page
Opens a content item from the home screen and verifies:
- Detail page loads within SLA
- Title / description / metadata visible
- Play / Watch Now button present
- Ratings or genre info visible
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class ContentDetailTest(BaseScenario):

    SCENARIO_ID   = "TC006"
    SCENARIO_NAME = "Content Detail Page"

    PLAY_BUTTONS = ["Watch Now", "Play", "Resume", "Start Watching",
                    "WATCH NOW", "PLAY"]
    METADATA_INDICATORS = ["Season", "Episode", "Genre", "Rating", "Duration",
                           "min", "HD", "4K", "IMDb", "Year", "Description",
                           "Synopsis", "Cast", "Director", "About"]
    DETAIL_INDICATORS = ["Watch Now", "Play", "Add to", "More Info",
                         "Resume", "Season", "Episode", "Description"]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Navigate to a content item ─────────────────────────────────
        self.step(
            "Navigate to content item on home row",
            action_fn=lambda: self._navigate_to_content(),
            expected_fn=lambda: self._inspector.get_content_count() > 0,
            timeout=8,
        )

        # ── 2. Open detail page ───────────────────────────────────────────
        passed, duration_ms = self.timed_step(
            "Content detail page loads",
            action_fn=lambda: self._open_detail(),
            expected_fn=lambda: self._on_detail_page(),
            sla_ms=3000,
            timeout=12,
            screenshot=True,
        )

        if not passed:
            self._result.finish()
            return self._result

        # ── 3. Play button present ────────────────────────────────────────
        self.step(
            "Play / Watch Now button is visible",
            lambda: None,
            expected_fn=lambda: self._inspector.any_text_visible(self.PLAY_BUTTONS) is not None,
            timeout=5,
            screenshot=True,
        )

        # ── 4. Metadata visible ───────────────────────────────────────────
        metadata_found = self._inspector.any_text_visible(self.METADATA_INDICATORS)
        self._result.steps.append(StepResult(
            "Content metadata visible (genre/rating/duration)",
            metadata_found is not None,
            f"Found: {metadata_found}" if metadata_found else "No metadata indicators found",
        ))

        # ── 5. Content title is shown ─────────────────────────────────────
        all_texts = self._inspector.get_all_text()
        has_title = len([t for t in all_texts if len(t) > 3]) > 2
        self._result.steps.append(StepResult(
            "Content title / description text is visible",
            has_title,
            f"{len(all_texts)} text elements visible" if has_title else "Too few text elements",
        ))
        if has_title:
            self._log.info(f"  Detail page texts: {all_texts[:8]}")

        # ── 6. Screenshot and back ────────────────────────────────────────
        self._take_screenshot("content_detail")
        self.step(
            "Back returns to browse screen",
            action_fn=lambda: self._safe_back(1),
            expected_fn=lambda: not self._on_detail_page(),
            timeout=8,
        )

        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _navigate_to_content(self):
        """Move to the first content row — use BACK to reach root, never HOME."""
        self._go_to_app_root()
        self._wait(1)
        self._remote.down(2, delay=0.4)
        self._remote.right(delay=0.4)
        self._wait(0.5)

    def _open_detail(self):
        """Press SELECT to open the detail page."""
        self._remote.select()
        self._wait(2)

    def _on_detail_page(self) -> bool:
        return self._inspector.any_text_visible(self.DETAIL_INDICATORS) is not None
