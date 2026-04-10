"""
TC012 — Subscription & Account Validation
Verifies account and subscription status without making any changes:
- Navigate to account/profile
- Verify subscription plan is shown and active
- Verify account email matches configured login
- Verify no paywall / upsell blocks content access
- Check that premium content is accessible (no "Subscribe to Watch" blocks)
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult
from config import config


class SubscriptionTest(BaseScenario):

    SCENARIO_ID   = "TC012"
    SCENARIO_NAME = "Subscription & Account Validation"

    ACCOUNT_NAV = ["Account", "Profile", "My Account", "Settings", "⚙"]

    SUBSCRIPTION_INDICATORS = [
        "Subscription", "Plan", "Premium", "Active", "Expires",
        "Valid till", "Member since", "Pro", "Basic", "Standard",
        "Subscribed", "Renewal", "Next billing",
    ]

    PAYWALL_INDICATORS = [
        "Subscribe to Watch", "Subscribe Now", "Upgrade to Watch",
        "Get Premium", "Buy Now", "Purchase", "Unlock",
        "Free Trial", "Start Trial",
    ]

    ACCOUNT_DETAILS = [
        "Email", "Username", "Name", "Phone", "Member ID",
    ]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")

        # ── 1. Navigate to Account/Profile ────────────────────────────────
        reached = self.step(
            "Navigate to Account / Profile",
            action_fn=lambda: self._go_to_account(),
            expected_fn=lambda: self._on_account_screen(),
            timeout=15,
            screenshot=True,
        )

        if not reached:
            self._result.finish()
            return self._result

        # ── 2. Subscription plan shown ────────────────────────────────────
        sub_visible = self._inspector.any_text_visible(self.SUBSCRIPTION_INDICATORS)
        self._result.steps.append(StepResult(
            "Subscription / Plan status is visible",
            sub_visible is not None,
            f"Found: {sub_visible}" if sub_visible else "No subscription info found",
        ))

        if sub_visible:
            # Log all visible text for report context
            all_texts = self._inspector.get_all_text()
            sub_related = [t for t in all_texts
                           if any(k.lower() in t.lower()
                                  for k in self.SUBSCRIPTION_INDICATORS)]
            self._log.info(f"  Subscription info: {sub_related}")

        # ── 3. Account email matches ──────────────────────────────────────
        email = config.login.email
        email_visible = self._inspector.is_text_visible(email) or \
                        self._inspector.is_text_visible(email.split("@")[0])
        self._result.steps.append(StepResult(
            f"Account email visible ({email})",
            email_visible,
            f"Email '{email}' found on screen" if email_visible
            else "Account email not displayed on screen",
        ))

        # ── 4. Account details section ────────────────────────────────────
        detail_found = self._inspector.any_text_visible(self.ACCOUNT_DETAILS)
        self._result.steps.append(StepResult(
            "Account details section loaded",
            detail_found is not None,
            f"Found field: {detail_found}" if detail_found else "No account detail fields found",
        ))

        self._take_screenshot("account_profile")

        # ── 5. Go to home — check no paywall on content ───────────────────
        self._remote.back(3)
        self._wait(1)
        self._go_to_app_root()
        self._wait(2)

        # Navigate into content to check for paywall
        self._remote.down(2, delay=0.4)
        self._remote.right(delay=0.4)
        self._wait(0.3)
        self._remote.select()
        self._wait(2)

        # ── 6. No paywall blocking content ───────────────────────────────
        paywall = self._inspector.any_text_visible(self.PAYWALL_INDICATORS)
        self._result.steps.append(StepResult(
            "No paywall / subscription prompt blocking content",
            paywall is None,
            "Content accessible without paywall" if paywall is None
            else f"Paywall detected: '{paywall}'",
        ))

        if paywall:
            self._take_screenshot("paywall_detected")
            self._log.warning(f"  Paywall detected: {paywall}")

        self._remote.back(2)
        self._result.finish()
        return self._result

    # ── Helpers ───────────────────────────────────────────────────────────

    def _go_to_account(self):
        """Navigate to Account via left sidebar bottom items."""
        self._go_to_app_root()
        self._wait(0.5)
        self._remote.left(1, delay=0.5)
        self._wait(0.4)
        self._ensure_in_app()
        for _ in range(15):
            focused = self._inspector.get_focused_element()
            if focused and any(s.lower() in focused.label.lower()
                               for s in self.ACCOUNT_NAV):
                self._remote.select()
                self._wait(2)
                return
            if self._inspector.any_text_visible(["Account", "Profile"]):
                self._remote.select()
                self._wait(2)
                return
            self._remote.right(delay=0.35)

    def _on_account_screen(self) -> bool:
        hints = self.ACCOUNT_NAV + self.SUBSCRIPTION_INDICATORS + self.ACCOUNT_DETAILS
        return self._inspector.any_text_visible(hints) is not None
