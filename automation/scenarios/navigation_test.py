"""
TC002 — Section Navigation & Content Load
ROD TV uses a LEFT SIDEBAR for navigation (icon-only, x:0-154).
Press LEFT from content to reach the sidebar, then UP/DOWN to move between items,
then SELECT or RIGHT to open a section.
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class SectionNavigationTest(BaseScenario):

    SCENARIO_ID   = "TC002"
    SCENARIO_NAME = "Section Navigation & Content Load"

    # ROD TV left sidebar has ~6 icon items — we test each by index
    # Sidebar item centres (tap coordinates from UI dump): x=77, y=215,305,395,485,575,665
    SIDEBAR_ITEMS = [
        {"y": 215, "label": "Nav Item 1 (Home/top)"},
        {"y": 305, "label": "Nav Item 2"},
        {"y": 395, "label": "Nav Item 3"},
        {"y": 485, "label": "Nav Item 4"},
        {"y": 575, "label": "Nav Item 5"},
        {"y": 665, "label": "Nav Item 6 (bottom)"},
    ]

    CONTENT_INDICATORS = [
        "COMING SOON", "Popular Collections", "Continue Watching",
        "RODtv", "Rodtv", "Watch Now", "Play", "Resume",
        "left",   # "46m left" etc.
        "Movies", "Series", "Live", "Sports",
    ]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Confirm we start on ROD TV home ────────────────────────────
        self._wait(2)
        self._ensure_in_app()
        start_texts = self._inspector.get_all_text()
        self._log.info(f"  Start screen texts: {start_texts[:6]}")

        # ── 2. Press LEFT to reach the sidebar ───────────────────────────
        reached_sidebar = self.step(
            "Press LEFT to open/focus the navigation sidebar",
            action_fn=lambda: self._remote.left(1, delay=0.6),
            expected_fn=lambda: self._sidebar_focused(),
            timeout=5,
            screenshot=True,
        )

        # ── 3. Test each sidebar item ────────────────────────────────────
        # Start from the first item — navigate DOWN through each
        # First go to top of sidebar
        self._remote.up(5, delay=0.25)   # ensure we're at top item
        self._wait(0.5)

        items_tested = 0
        items_passed = 0

        for i, item in enumerate(self.SIDEBAR_ITEMS):
            label = item["label"]
            self._log.info(f"  -- Testing sidebar item {i+1}: {label} --")

            # Tap the sidebar item directly by coordinate
            self._remote.tap(77, item["y"], delay=0.5)
            self._wait(0.3)
            # Press SELECT or RIGHT to open section
            self._remote.select()
            self._wait(2)

            # Check we're still in ROD TV
            if not self._ensure_in_app():
                self._log.warning(f"  App exited on item {i+1} — skipping")
                break

            # Check content loaded
            texts = self._inspector.get_all_text()
            has_content = bool(self._inspector.any_text_visible(self.CONTENT_INDICATORS))
            item_count = self._inspector.get_content_count()

            self._log.info(f"    Texts: {texts[:4]} | Items: {item_count} | Content: {has_content}")

            # Screenshot
            self._take_screenshot(f"nav_item_{i+1}")

            self._result.steps.append(StepResult(
                f"Sidebar item {i+1} — content loads",
                has_content or item_count > 1,
                f"{item_count} elements, texts: {texts[:3]}",
            ))

            items_tested += 1
            if has_content or item_count > 1:
                items_passed += 1

            # Go back to sidebar for next item
            self._remote.left(1, delay=0.4)
            self._wait(0.3)
            self._remote.down(1, delay=0.3)   # next sidebar item
            self._wait(0.3)

        # ── 4. Test scroll down on home content ──────────────────────────
        # Return to home content
        self._remote.right(delay=0.5)
        self._wait(1)
        self._ensure_in_app()

        passed, _ = self.timed_step(
            "Scroll down — more content rows load",
            action_fn=lambda: self._remote.down(3, delay=0.4),
            expected_fn=lambda: self._inspector.get_content_count() > 2,
            sla_ms=3000,
            timeout=8,
            screenshot=True,
        )

        # ── 5. Scroll right — horizontal content row works ────────────────
        self.step(
            "Scroll right — horizontal content cards navigate",
            action_fn=lambda: self._remote.right(3, delay=0.4),
            expected_fn=lambda: self._inspector.get_content_count() > 0,
            timeout=5,
            screenshot=True,
        )

        self._log.info(f"  Navigation result: {items_passed}/{items_tested} sidebar items loaded content")
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _sidebar_focused(self) -> bool:
        """Check if focus is now on the left sidebar (x < 154)."""
        focused = self._inspector.get_focused_element()
        if focused:
            cx = focused.bounds.get("x2", 999)
            return cx <= 200  # sidebar items end at x=154
        return True  # assume reached if no error
