"""
TC009 — Settings & Profile
Tests the settings and profile section:
- Navigate to Settings
- Verify settings options load
- Check account/profile info is visible
- Navigate sub-settings (video quality, language, etc.)
- Verify back navigation works from all settings screens
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult


class SettingsTest(BaseScenario):

    SCENARIO_ID   = "TC009"
    SCENARIO_NAME = "Settings & Profile"

    SETTINGS_NAV = ["Settings", "Profile", "Account", "My Account",
                    "⚙", "Preferences"]

    SETTINGS_ITEMS = [
        "Account", "Profile", "Subscription", "Plan",
        "Video Quality", "Playback", "Language", "Audio",
        "Subtitles", "Captions", "Notifications", "Privacy",
        "About", "Help", "Support", "Sign Out", "Logout",
        "Terms", "Version", "App Version",
    ]

    SUB_SETTINGS_GROUPS = [
        ("Video Quality", ["Auto", "Low", "Medium", "High", "HD", "4K", "720p", "1080p"]),
        ("Language",      ["English", "Arabic", "Hindi", "French", "Spanish"]),
        ("Subtitles",     ["Off", "On", "English", "None"]),
    ]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Navigate to Settings ───────────────────────────────────────
        reached = self.step(
            "Navigate to Settings section",
            action_fn=lambda: self._go_to_settings(),
            expected_fn=lambda: self._on_settings_screen(),
            timeout=15,
            screenshot=True,
        )

        if not reached:
            self._log.warning("  Settings section not found — skipping TC009")
            self._result.finish()
            return self._result

        # ── 2. Settings page loads ────────────────────────────────────────
        self.step(
            "Settings page loads with options",
            lambda: None,
            expected_fn=lambda: self._inspector.get_content_count() > 0,
            timeout=5,
            screenshot=True,
        )

        # ── 3. Identify visible settings items ────────────────────────────
        visible_settings = []
        for item in self.SETTINGS_ITEMS:
            if self._inspector.is_text_visible(item):
                visible_settings.append(item)

        self._log.info(f"  Visible settings: {visible_settings}")
        self._result.steps.append(StepResult(
            f"Settings items visible ({len(visible_settings)} found)",
            len(visible_settings) >= 2,
            ", ".join(visible_settings) if visible_settings else "No recognised settings items found",
        ))

        # ── 4. Account / Profile info visible ────────────────────────────
        profile_indicators = ["Account", "Profile", "Email", "Subscription",
                               "Plan", "Member", "santosh"]
        profile_found = self._inspector.any_text_visible(profile_indicators)
        self._result.steps.append(StepResult(
            "Account / Profile info is shown",
            profile_found is not None,
            f"Found: {profile_found}" if profile_found else "No profile info visible",
        ))

        # ── 5. Open Video Quality setting ─────────────────────────────────
        self._test_sub_setting("Video Quality",
                               ["Auto", "Low", "Medium", "High", "HD", "720p", "1080p", "4K"])

        # ── 6. Open Language setting ──────────────────────────────────────
        self._test_sub_setting("Language",
                               ["English", "Arabic", "Hindi", "French", "Spanish", "Auto"])

        # ── 7. Sign Out button visible (but don't press it) ───────────────
        signout_present = self._inspector.any_text_visible(
            ["Sign Out", "Logout", "Log Out", "SIGN OUT"])
        self._result.steps.append(StepResult(
            "Sign Out option is present",
            signout_present is not None,
            f"Found: {signout_present}" if signout_present else "Sign Out button not found",
        ))

        # ── 8. Back to home ───────────────────────────────────────────────
        self.step(
            "Back navigation returns from Settings",
            action_fn=lambda: self._remote.back(3),
            expected_fn=lambda: not self._on_settings_screen(),
            timeout=8,
        )

        self._take_screenshot("settings_complete")
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _go_to_settings(self):
        """Navigate to Settings via the left sidebar."""
        from config import config
        sidebar_x = config.client.sidebar_x
        # Try known settings-like sidebar labels in priority order
        for label in ["Account Info", "Settings", "Account", "Profile"]:
            item = config.client.sidebar_item(label)
            if item:
                settings_y = item.get("y", 665)
                break
        else:
            settings_y = 665   # last-resort fallback

        self._go_to_app_root()
        self._wait(0.5)
        self._remote.left(1, delay=0.5)
        self._wait(0.4)
        self._ensure_in_app()
        self._remote.tap(sidebar_x, settings_y, delay=0.5)
        self._wait(0.3)
        self._remote.select()
        self._wait(2)
        if self._on_settings_screen():
            return
        # Try adjacent sidebar items if first tap didn't land on settings
        for offset in [-90, 90]:
            self._remote.left(1, delay=0.3)
            self._remote.tap(sidebar_x, settings_y + offset, delay=0.5)
            self._wait(0.3)
            self._remote.select()
            self._wait(2)
            if self._on_settings_screen():
                return
            self._remote.left(1, delay=0.3)

    def _on_settings_screen(self) -> bool:
        all_hints = self.SETTINGS_NAV + self.SETTINGS_ITEMS
        return self._inspector.any_text_visible(all_hints) is not None

    def _test_sub_setting(self, setting_name: str, expected_options: list):
        """Navigate into a sub-setting and verify options are listed."""
        # Find and select the setting
        el = self._inspector.find_by_text(setting_name)
        if not el:
            return   # Not present in this app's settings

        self._log.info(f"  Testing sub-setting: {setting_name}")

        # Navigate to it
        for _ in range(8):
            focused = self._inspector.get_focused_element()
            if focused and setting_name.lower() in focused.label.lower():
                self._remote.select()
                self._wait(1.5)
                options_visible = self._inspector.any_text_visible(expected_options)
                self._result.steps.append(StepResult(
                    f'"{setting_name}" sub-menu opens with options',
                    options_visible is not None,
                    f"Found option: {options_visible}" if options_visible
                    else f"No options visible ({expected_options[:3]}...)",
                    screenshot=False,
                ))
                self._take_screenshot(f"settings_{setting_name.lower().replace(' ', '_')}")
                self._remote.back()
                self._wait(1)
                return
            self._remote.down(delay=0.35)
