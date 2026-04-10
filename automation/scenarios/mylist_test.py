"""
TC007 — My List / Watchlist
Tests adding content to the watchlist / My List:
- Open a content detail page
- Find and press "Add to List" / "Watchlist" button
- Verify confirmation feedback
- Navigate to My List section
- Verify the added content appears there
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class MyListTest(BaseScenario):

    SCENARIO_ID   = "TC007"
    SCENARIO_NAME = "My List / Watchlist Management"

    ADD_BUTTONS = [
        "Add to List", "Add to Watchlist", "+ List", "Watchlist",
        "Add to My List", "+ My List", "Save", "Bookmark",
        "ADD TO LIST", "ADD TO WATCHLIST",
    ]
    REMOVE_BUTTONS = [
        "Remove from List", "Remove", "In My List", "✓ List",
        "Remove from Watchlist", "Saved",
    ]
    CONFIRMATION_TEXTS = [
        "Added", "Saved to", "In your list", "Added to list",
        "Added to My List", "Saved", "In My List",
    ]
    MYLIST_NAV = ["My List", "Watchlist", "My Watchlist", "Saved", "Bookmarks"]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Open a content detail page ────────────────────────────────
        self.step(
            "Open content detail page",
            action_fn=lambda: self._open_content_detail(),
            expected_fn=lambda: self._on_detail_page(),
            timeout=15,
            screenshot=True,
        )

        # ── 2. Add to List button visible ─────────────────────────────────
        add_btn_visible = self.step(
            "Add to List button is present",
            lambda: None,
            expected_fn=lambda: self._find_add_button() is not None,
            timeout=5,
            screenshot=True,
        )

        if not add_btn_visible:
            self._log.warning("  No Add to List button found — My List feature may be absent")
            self._result.steps.append(StepResult(
                "My List feature availability",
                False,
                "Add to List / Watchlist button not found on detail page",
            ))
            self._result.finish()
            return self._result

        # ── 3. Press Add to List ──────────────────────────────────────────
        # Record title before adding
        title_before = self._get_content_title()
        self._log.info(f"  Adding to list: '{title_before}'")

        self.step(
            "Press Add to List button",
            action_fn=lambda: self._press_add_button(),
            timeout=5,
            screenshot=True,
        )

        # ── 4. Confirmation feedback ──────────────────────────────────────
        self.step(
            "Confirmation shown (added to list)",
            lambda: None,
            expected_fn=lambda: (
                self._inspector.any_text_visible(self.CONFIRMATION_TEXTS) is not None
                or self._inspector.any_text_visible(self.REMOVE_BUTTONS) is not None
            ),
            timeout=6,
            screenshot=True,
        )

        # ── 5. Navigate to My List section ───────────────────────────────
        self._remote.back(2)
        self._wait(1)
        reached_mylist = self.step(
            "Navigate to My List section",
            action_fn=lambda: self._go_to_my_list(),
            expected_fn=lambda: self._inspector.any_text_visible(self.MYLIST_NAV) is not None,
            timeout=15,
            screenshot=True,
        )

        # ── 6. Content appears in My List ─────────────────────────────────
        if reached_mylist and title_before:
            self.step(
                f'"{title_before}" appears in My List',
                lambda: None,
                expected_fn=lambda: self._inspector.is_text_visible(title_before),
                timeout=5,
                screenshot=True,
            )
        elif reached_mylist:
            count = self._inspector.get_content_count()
            self._result.steps.append(StepResult(
                "My List has content items",
                count > 0,
                f"{count} items visible in My List",
            ))

        self._take_screenshot("mylist_complete")
        self._remote.back(3)
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _open_content_detail(self):
        self._go_to_app_root()
        self._wait(1)
        self._remote.down(2, delay=0.4)
        self._remote.right(delay=0.4)
        self._wait(0.5)
        self._remote.select()
        self._wait(2)

    def _on_detail_page(self) -> bool:
        indicators = ["Watch Now", "Play", "Resume", "Add to", "Season", "Episode"]
        return self._inspector.any_text_visible(indicators) is not None

    def _find_add_button(self):
        for label in self.ADD_BUTTONS:
            el = self._inspector.find_by_text(label)
            if el:
                return el
        return None

    def _press_add_button(self):
        btn = self._find_add_button()
        if btn:
            cx, cy = btn.center
            self._remote.tap(cx, cy, delay=0.5)
        else:
            # Try D-pad navigation to find it
            for _ in range(6):
                focused = self._inspector.get_focused_element()
                if focused and any(t.lower() in focused.label.lower()
                                   for t in ["list", "watchlist", "save"]):
                    self._remote.select()
                    return
                self._remote.right(delay=0.35)

    def _get_content_title(self) -> str:
        texts = self._inspector.get_all_text()
        # The title is usually the longest text near the top
        candidates = [t for t in texts if 3 < len(t) < 80
                      and t not in ["Watch Now", "Play", "Add to List", "More Info"]]
        return candidates[0] if candidates else ""

    def _go_to_my_list(self):
        """Navigate via left sidebar — tap each item until My List screen found."""
        self._go_to_app_root()
        self._wait(0.5)
        self._remote.left(1, delay=0.5)
        self._wait(0.4)
        self._ensure_in_app()
        for _ in range(12):
            if self._inspector.any_text_visible(self.MYLIST_NAV):
                focused = self._inspector.get_focused_element()
                if focused and any(s.lower() in focused.label.lower()
                                   for s in self.MYLIST_NAV):
                    self._remote.select()
                    self._wait(1.5)
                    return
                self._remote.select()
                self._wait(1.5)
                return
            self._remote.right(delay=0.35)
