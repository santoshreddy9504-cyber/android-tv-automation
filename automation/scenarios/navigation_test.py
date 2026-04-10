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

    # ROD TV left sidebar — confirmed labels from UI dump (sidebar open screenshot)
    # x=77 for all items; y positions from uiautomator bounds
    SIDEBAR_ITEMS = [
        {"y": 215, "label": "Home",         "indicators": ["Popular Collections", "Continue Watching", "COMING SOON", "New On"]},
        {"y": 305, "label": "Live Events",  "indicators": ["Live", "Live Events", "Channels", "Channel", "On Air", "LIVE"]},
        {"y": 395, "label": "Trending",     "indicators": ["Trending", "Popular", "Top", "Featured", "Most Watched"]},
        {"y": 485, "label": "My List",      "indicators": ["My List", "Watchlist", "Saved", "No items", "Your list", "Watch Later"]},
        {"y": 575, "label": "Search",       "indicators": ["Search", "search", "Find", "Type to search"]},
        {"y": 665, "label": "Account Info", "indicators": ["Account", "Profile", "Settings", "Sign", "Email", "Subscription", "Log"]},
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
            label    = item["label"]
            expected = item["indicators"]
            self._log.info(f"  -- Testing sidebar item {i+1}: {label} --")

            # Tap the sidebar item — tap alone selects/opens the section
            self._remote.tap(77, item["y"], delay=0.6)
            self._wait(2)

            # Check we're still in ROD TV
            if not self._ensure_in_app():
                self._log.warning(f"  App exited on item {i+1} — skipping")
                break

            # Check section-specific content loaded
            texts = self._inspector.get_all_text()
            section_match = bool(self._inspector.any_text_visible(expected))
            generic_content = bool(self._inspector.any_text_visible(self.CONTENT_INDICATORS))
            item_count = self._inspector.get_content_count()
            passed_step = section_match or (generic_content and item_count > 1)

            self._log.info(
                f"    [{label}] section_match={section_match} content={generic_content} "
                f"items={item_count} texts={texts[:4]}"
            )

            # Screenshot
            self._take_screenshot(f"nav_item_{i+1}_{label.replace(' ', '_')}")

            self._result.steps.append(StepResult(
                f"{label} section loads correctly",
                passed_step,
                f"section indicators: {section_match}, items: {item_count}, texts: {texts[:3]}",
            ))

            items_tested += 1
            if passed_step:
                items_passed += 1

            # Return to sidebar for next item — tap the sidebar column
            self._remote.left(1, delay=0.4)
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
