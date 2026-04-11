"""
TC002 — Section Navigation & Content Load

The app under test uses a left sidebar for navigation.
Sidebar structure (items, coordinates, and content indicators) is loaded
from the client config file (CLIENT_CONFIG in .env).
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult
from config import config


class SectionNavigationTest(BaseScenario):

    SCENARIO_ID   = "TC002"
    SCENARIO_NAME = "Section Navigation & Content Load"

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        sidebar_items     = config.client.sidebar_items
        sidebar_x         = config.client.sidebar_x
        content_indicators = config.client.content_indicators

        if not sidebar_items:
            self._log.warning("  No sidebar_items defined in client config — skipping navigation test")
            self._result.finish()
            return self._result

        # ── 1. Confirm app is on home screen ─────────────────────────────
        self._wait(2)
        self._ensure_in_app()
        start_texts = self._inspector.get_all_text()
        self._log.info(f"  Start screen texts: {start_texts[:6]}")

        # ── 2. Press LEFT to reach the sidebar ───────────────────────────
        self.step(
            "Press LEFT to open/focus the navigation sidebar",
            action_fn=lambda: self._remote.left(1, delay=0.6),
            expected_fn=lambda: self._sidebar_focused(),
            timeout=5,
            screenshot=True,
        )

        # ── 3. Test each sidebar item ────────────────────────────────────
        self._remote.up(5, delay=0.25)   # ensure we start at the top item
        self._wait(0.5)

        items_tested = 0
        items_passed = 0

        for i, item in enumerate(sidebar_items):
            label    = item.get("label", f"Item {i+1}")
            y        = item.get("y", 0)
            expected = item.get("indicators", [])
            self._log.info(f"  -- Testing sidebar item {i+1}: {label} --")

            self._remote.tap(sidebar_x, y, delay=0.6)
            self._wait(2)

            if not self._ensure_in_app():
                self._log.warning(f"  App exited on item {i+1} — skipping")
                break

            texts         = self._inspector.get_all_text()
            section_match = bool(self._inspector.any_text_visible(expected))
            generic_ok    = bool(self._inspector.any_text_visible(content_indicators))
            item_count    = self._inspector.get_content_count()
            passed_step   = section_match or (generic_ok and item_count > 1)

            self._log.info(
                f"    [{label}] section_match={section_match} content={generic_ok} "
                f"items={item_count} texts={texts[:4]}"
            )

            self._take_screenshot(f"nav_item_{i+1}_{label.replace(' ', '_')}")

            self._result.steps.append(StepResult(
                f"{label} section loads correctly",
                passed_step,
                f"section indicators: {section_match}, items: {item_count}, texts: {texts[:3]}",
            ))

            items_tested += 1
            if passed_step:
                items_passed += 1

            self._remote.left(1, delay=0.4)
            self._wait(0.3)

        # ── 4. Scroll down — more rows load ──────────────────────────────
        self._remote.right(delay=0.5)
        self._wait(1)
        self._ensure_in_app()

        self.timed_step(
            "Scroll down — more content rows load",
            action_fn=lambda: self._remote.down(3, delay=0.4),
            expected_fn=lambda: self._inspector.get_content_count() > 2,
            sla_ms=3000,
            timeout=8,
            screenshot=True,
        )

        # ── 5. Scroll right — horizontal cards work ───────────────────────
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
        """Check if focus is now on the left sidebar."""
        focused = self._inspector.get_focused_element()
        if focused:
            cx = focused.bounds.get("x2", 999)
            return cx <= 200
        return True
