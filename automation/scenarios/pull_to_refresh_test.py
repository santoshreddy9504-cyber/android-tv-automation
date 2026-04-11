"""
TC013 — Pull-to-Refresh

Verifies that a downward swipe gesture at the top of a scrollable
content list triggers a data refresh in the ROD TV app.

Test covers three surfaces where pull-to-refresh is commonly expected:
  1. Home screen  — swipe down on the main content area
  2. My List      — swipe down on the watchlist
  3. Trending     — swipe down on the trending row

Each sub-test:
  a) navigates to the target screen,
  b) scrolls to the very top (UP × 10),
  c) captures a "before" content fingerprint,
  d) performs a pull-to-refresh swipe,
  e) waits up to 6 s for a loading indicator OR a content change,
  f) captures an "after" fingerprint and records PASS/FAIL.
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


# Texts that indicate an active data-load / refresh is in progress
LOADING_INDICATORS = [
    "Loading", "Refreshing", "Please wait",
    "Updating", "Fetching", "Syncing",
]

# Texts that confirm content is present after refresh
CONTENT_INDICATORS = [
    "Popular Collections", "Continue Watching", "COMING SOON",
    "Watch Now", "Play", "Resume", "Movies", "Series",
    "Live", "Sports", "My List", "Watchlist", "Trending",
    "Top", "Featured",
]

# Sidebar tap targets  (same co-ordinates used by TC002)
SIDEBAR = {
    "Home":     (77, 215),
    "Trending": (77, 395),
    "My List":  (77, 485),
}


class PullToRefreshTest(BaseScenario):

    SCENARIO_ID   = "TC013"
    SCENARIO_NAME = "Pull-to-Refresh"

    def run(self) -> "ScenarioResult":
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        self._wait(2)
        self._ensure_in_app()

        # Detect physical screen resolution so the swipe lands in the right place
        width, height = self._get_screen_resolution()
        self._log.info(f"  Screen resolution: {width}x{height}")

        # ── 1. Home screen pull-to-refresh ───────────────────────────────
        self._navigate_to("Home")
        self._step_pull_to_refresh("Home screen", width, height)

        # ── 2. My List pull-to-refresh ───────────────────────────────────
        self._navigate_to("My List")
        self._step_pull_to_refresh("My List", width, height)

        # ── 3. Trending pull-to-refresh ──────────────────────────────────
        self._navigate_to("Trending")
        self._step_pull_to_refresh("Trending", width, height)

        # Return to home so the next scenario starts cleanly
        self._go_to_app_root()
        self._result.finish()
        return self._result

    # ── Sub-steps ─────────────────────────────────────────────────────────

    def _step_pull_to_refresh(self, surface: str, width: int, height: int):
        """Run the full pull-to-refresh verification for one surface."""

        # a) Scroll to the very top
        self.step(
            f"{surface}: scroll to top",
            action_fn=lambda: self._remote.up(10, delay=0.2),
        )
        self._wait(1)

        # b) Snapshot content fingerprint before refresh
        before_texts = set(self._inspector.get_all_text())
        before_count = self._inspector.get_content_count()
        self._log.info(
            f"  [{surface}] before: {before_count} items, "
            f"sample={list(before_texts)[:4]}"
        )

        # c) Take a "before" screenshot
        self._take_screenshot(f"ptr_{surface.replace(' ', '_')}_before")

        # d) Perform the pull-to-refresh swipe
        self.step(
            f"{surface}: pull-to-refresh swipe",
            action_fn=lambda: self._remote.pull_to_refresh(width, height, delay=0.5),
        )

        # e) Wait for loading indicator OR content change (up to 6 s)
        refreshed = self._wait_for_refresh(surface, before_texts, before_count)

        # f) "After" screenshot + record result
        self._take_screenshot(f"ptr_{surface.replace(' ', '_')}_after")
        after_texts = set(self._inspector.get_all_text())
        after_count = self._inspector.get_content_count()
        self._log.info(
            f"  [{surface}] after: {after_count} items, "
            f"sample={list(after_texts)[:4]}, refreshed={refreshed}"
        )

        self._result.steps.append(StepResult(
            f"{surface}: content refreshed after pull-to-refresh",
            passed=refreshed,
            message=(
                f"before={before_count} items → after={after_count} items"
                if refreshed
                else "No loading indicator or content change detected within 6 s"
            ),
        ))

    # ── Navigation helpers ─────────────────────────────────────────────────

    def _navigate_to(self, section: str):
        """Tap the sidebar icon for the given section and wait for it to load."""
        x, y = SIDEBAR[section]
        self._log.info(f"  Navigating to {section} …")
        # Open sidebar
        self._remote.left(1, delay=0.5)
        self._wait(0.3)
        # Tap section icon
        self._remote.tap(x, y, delay=0.7)
        self._wait(2)
        # Move focus into the content area
        self._remote.right(delay=0.4)
        self._wait(1)
        self._ensure_in_app()

    # ── Detection helpers ──────────────────────────────────────────────────

    def _wait_for_refresh(self, surface: str, before_texts: set,
                          before_count: int, timeout: float = 6.0) -> bool:
        """
        Poll up to `timeout` seconds for evidence of a refresh:
          • A loading/spinner text appears and then disappears, OR
          • The content fingerprint changes (text set or item count differs).
        Returns True if refresh was detected.
        """
        deadline = time.time() + timeout
        saw_loading = False

        while time.time() < deadline:
            time.sleep(0.5)
            current_texts = set(self._inspector.get_all_text())
            current_count = self._inspector.get_content_count()

            # Check for transient loading indicator
            if not saw_loading:
                loading = self._inspector.any_text_visible(LOADING_INDICATORS)
                if loading:
                    self._log.info(f"  [{surface}] loading indicator: '{loading.text}'")
                    saw_loading = True

            # Content fingerprint changed → refresh happened
            if current_texts != before_texts or current_count != before_count:
                self._log.info(
                    f"  [{surface}] content changed "
                    f"({before_count} → {current_count} items)"
                )
                return True

        # If we saw a loading indicator during the window, count it as a pass
        # even if the final content set looks the same (same data refreshed).
        return saw_loading

    def _get_screen_resolution(self) -> tuple:
        """
        Query the device display size via `wm size`.
        Falls back to 1920×1080 if the command fails.
        """
        try:
            out = self._adb.shell("wm size")
            # Expected: "Physical size: 1920x1080"  or  "Override size: ..."
            for line in out.splitlines():
                if "size:" in line.lower():
                    parts = line.split(":")[-1].strip().split("x")
                    if len(parts) == 2:
                        return int(parts[0]), int(parts[1])
        except Exception as exc:
            self._log.warning(f"Could not detect screen resolution: {exc}")
        return 1920, 1080
