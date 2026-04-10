"""
TC005 — Search Functionality
Tests the search feature end-to-end:
- Navigate to Search section
- Enter a search query via on-screen keyboard or ADB text input
- Verify results appear within SLA
- Select a result and verify detail page loads
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class SearchTest(BaseScenario):

    SCENARIO_ID   = "TC005"
    SCENARIO_NAME = "Search Functionality"

    SEARCH_QUERY = "movie"

    SEARCH_ENTRY_POINTS = ["Search", "search", "🔍", "Find"]
    RESULT_INDICATORS   = ["Watch Now", "Play", "Resume", "More Info",
                           "Episode", "Season", "Series", "Movie"]
    NO_RESULT_INDICATORS = ["No results", "Nothing found", "Try a different",
                             "No content", "0 results"]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Navigate to Search ─────────────────────────────────────────
        reached = self.step(
            "Navigate to Search section",
            action_fn=lambda: self._go_to_search(),
            expected_fn=lambda: self._on_search_screen(),
            timeout=15,
            screenshot=True,
        )

        if not reached:
            self._log.warning("  Search section not reachable — skipping TC005")
            self._result.finish()
            return self._result

        # ── 2. Enter search query ─────────────────────────────────────────
        self.step(
            f'Enter search query "{self.SEARCH_QUERY}"',
            action_fn=lambda: self._type_search(self.SEARCH_QUERY),
            timeout=8,
            screenshot=True,
        )

        # ── 3. Results appear within SLA ──────────────────────────────────
        passed, duration_ms = self.timed_step(
            "Search results load",
            action_fn=lambda: None,
            expected_fn=lambda: self._has_results(),
            sla_ms=4000,
            timeout=15,
            screenshot=True,
        )

        # ── 4. No error state ─────────────────────────────────────────────
        self.step(
            "No 'No results' error shown",
            lambda: None,
            expected_fn=lambda: not self._inspector.any_text_visible(self.NO_RESULT_INDICATORS),
        )

        # ── 5. Select first result ────────────────────────────────────────
        if passed:
            self.step(
                "Select first search result",
                action_fn=lambda: self._select_first_result(),
                expected_fn=lambda: self._inspector.any_text_visible(
                    self.RESULT_INDICATORS) is not None,
                timeout=10,
                screenshot=True,
            )

        # ── 6. Back to home ───────────────────────────────────────────────
        self.step(
            "Back navigation returns from search",
            action_fn=lambda: self._go_to_app_root(),
            timeout=8,
        )

        self._take_screenshot("search_complete")
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _go_to_search(self):
        """Navigate to Search within the ROD TV app via the left sidebar (y=575)."""
        self._go_to_app_root()
        self._wait(0.5)
        self._remote.left(1, delay=0.5)   # open sidebar
        self._wait(0.4)
        self._ensure_in_app()
        # Tap the Search sidebar item (5th icon, y=575) — tap alone selects it
        self._remote.tap(77, 575, delay=0.5)
        self._wait(1.5)
        if self._on_search_screen():
            return
        # If not on search yet, try pressing SELECT to confirm
        self._remote.select()
        self._wait(1.5)

    def _on_search_screen(self) -> bool:
        texts = self._inspector.get_all_text()
        combined = " ".join(texts).lower()
        return any(k in combined for k in ["search", "find", "type to search", "q"])

    def _type_search(self, query: str):
        """Type into the search field — try tap on EditText first, else keycode."""
        fields = self._inspector.find_input_fields()
        if fields:
            cx, cy = fields[0].center
            self._remote.tap(cx, cy, delay=0.5)
        self._remote.type_text(query)
        # Some search UIs auto-search; others need ENTER
        self._wait(1.0)
        self._remote.press_keycode(66, delay=0.5)   # ENTER

    def _has_results(self) -> bool:
        if self._inspector.any_text_visible(self.RESULT_INDICATORS):
            return True
        return self._inspector.get_content_count() > 2

    def _select_first_result(self):
        """Navigate to and select the first result item."""
        self._remote.down(delay=0.4)
        self._wait(0.3)
        self._remote.select()
        self._wait(2)
