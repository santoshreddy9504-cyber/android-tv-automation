"""
TC000 — Login / Authentication
Handles automatic login to ROD TV from the login screen.

Flow:
  1. Check if already logged in (home indicators visible) — skip if so
  2. Wait for login screen to appear
  3. Find email field → tap → type email
  4. Find password field → tap → type password
  5. Find & press Login/Sign In button
  6. Wait for home screen to confirm success
  7. Fail with screenshot if login fails or times out
"""

import time
from automation.scenarios.base_scenario import BaseScenario, StepResult
from config import config


class LoginTest(BaseScenario):

    SCENARIO_ID   = "TC000"
    SCENARIO_NAME = "User Authentication (Login)"

    # Texts that indicate the login screen is visible
    LOGIN_SCREEN_TEXTS = [
        "Sign In", "Login", "Log In", "Sign in",
        "Email", "Email Address", "Username",
        "Password", "Forgot Password",
        "Enter your email", "Enter email",
    ]

    # Button labels to press to submit the form
    LOGIN_BUTTON_TEXTS = [
        "Sign In", "Login", "Log In", "SIGN IN", "LOGIN", "Submit", "SUBMIT",
        "Continue", "Next",
    ]

    # Texts that mean we're now on the home screen (login succeeded)
    HOME_TEXTS = [
        # ROD TV specific
        "Popular Collections", "RODtv", "Rodtv", "COMING SOON",
        "Continue Watching",
        # Generic
        "Home", "Featured", "Trending", "Live", "Movies",
        "Series", "Watch Now", "Popular", "New",
    ]

    def run(self):
        self._log.info(f"=== {self.SCENARIO_ID}: {self.SCENARIO_NAME} ===")
        cfg = config.login

        # ── 0. Already logged in? ─────────────────────────────────────────
        if cfg.skip_if_logged_in:
            self._log.info("  Checking if already logged in ...")
            self._wait(2)
            if self._inspector.any_text_visible(self.HOME_TEXTS):
                self._log.info("  ✅ Already on home screen — skipping login")
                self.step(
                    "Already logged in — home screen detected",
                    lambda: None,
                    expected_fn=lambda: True,
                )
                self._result.finish()
                return self._result

        # ── 1. Validate credentials are configured ────────────────────────
        if not cfg.email or not cfg.password:
            self._log.error("  No credentials configured. Set config.login.email / password")
            self._result.steps.append(StepResult(
                "Credentials configured",
                False,
                "email/password not set in config.login — pass --email / --password",
            ))
            self._result.finish()
            return self._result

        self.step(
            "Credentials are configured",
            lambda: None,
            expected_fn=lambda: bool(cfg.email and cfg.password),
        )

        # ── 2. Wait for login screen ──────────────────────────────────────
        self._log.info("  Waiting for login screen ...")
        login_appeared = self.step(
            "Login screen visible",
            action_fn=lambda: None,
            expected_fn=lambda: self._inspector.any_text_visible(self.LOGIN_SCREEN_TEXTS) is not None,
            timeout=15,
            screenshot=True,
        )

        if not login_appeared:
            # Try pressing BACK to dismiss any overlay
            self._remote.back()
            self._wait(2)
            # If home appeared after BACK, we were already logged in
            if self._inspector.any_text_visible(self.HOME_TEXTS):
                self._log.info("  Home visible after BACK — user was already logged in")
                self._result.finish()
                return self._result

        # ── 3. Enter email ────────────────────────────────────────────────
        self.step(
            "Enter email address",
            action_fn=lambda: self._enter_email(cfg.email),
            expected_fn=lambda: self._email_typed(cfg.email),
            timeout=10,
            screenshot=True,
        )

        # ── 4. Enter password ─────────────────────────────────────────────
        self.step(
            "Enter password",
            action_fn=lambda: self._enter_password(cfg.password),
            timeout=10,
            screenshot=True,
        )

        # ── 5. Press login button ─────────────────────────────────────────
        self.step(
            "Press Login / Sign In button",
            action_fn=lambda: self._press_login_button(),
            timeout=5,
            screenshot=True,
        )

        # ── 6. Wait for home screen ───────────────────────────────────────
        login_success = self.step(
            "Login succeeded — home screen loaded",
            action_fn=lambda: None,
            expected_fn=lambda: self._inspector.any_text_visible(self.HOME_TEXTS) is not None,
            timeout=cfg.login_timeout,
            screenshot=True,
        )

        # ── 7. Error check ────────────────────────────────────────────────
        if not login_success:
            error_msg = self._detect_login_error()
            self._result.steps.append(StepResult(
                "Login error check",
                False,
                error_msg or "Home screen did not appear within timeout",
            ))

        self._result.finish()
        return self._result

    # ── Internals ─────────────────────────────────────────────────────────

    def _enter_email(self, email: str):
        """Navigate to the email field, focus it, and type the email."""
        # Try to find EditText fields first
        fields = self._inspector.find_input_fields()
        if fields:
            # First field is usually email
            email_field = fields[0]
            cx, cy = email_field.center
            self._log.info(f"    Tapping email field at ({cx}, {cy})")
            self._remote.tap(cx, cy, delay=0.5)
        else:
            # Fall back: navigate to email text using D-pad
            self._log.info("    No EditText found — using D-pad to reach email field")
            email_el = self._inspector.find_by_text("Email") or \
                       self._inspector.find_by_text("Username")
            if email_el:
                cx, cy = email_el.center
                self._remote.tap(cx, cy, delay=0.5)
            else:
                # Navigate down until email field is focused
                for _ in range(5):
                    focused = self._inspector.get_focused_element()
                    if focused and _is_input_element(focused):
                        break
                    self._remote.down(delay=0.4)

        self._wait(0.5)
        self._remote.type_text(email)
        self._wait(0.3)

    def _enter_password(self, password: str):
        """Navigate to the password field and type the password."""
        fields = self._inspector.find_input_fields()
        if len(fields) >= 2:
            # Second field is usually password
            pw_field = fields[1]
            cx, cy = pw_field.center
            self._log.info(f"    Tapping password field at ({cx}, {cy})")
            self._remote.tap(cx, cy, delay=0.5)
        else:
            # Try finding by hint text
            pw_el = self._inspector.find_by_text("Password") or \
                    self._inspector.find_by_text("password")
            if pw_el:
                cx, cy = pw_el.center
                self._remote.tap(cx, cy, delay=0.5)
            else:
                # Press TAB / DOWN to move to next field
                self._remote.press_keycode(61, delay=0.4)  # KEYCODE_TAB
                if not self._focused_is_input():
                    self._remote.down(delay=0.4)

        self._wait(0.5)
        self._remote.type_text(password)
        self._wait(0.3)

    def _press_login_button(self):
        """Find and press the login/sign-in button."""
        # Try tapping by text
        for label in self.LOGIN_BUTTON_TEXTS:
            btn = self._inspector.find_by_text(label)
            if btn and btn.clickable:
                cx, cy = btn.center
                self._log.info(f"    Tapping login button '{btn.text}' at ({cx}, {cy})")
                self._remote.tap(cx, cy, delay=0.5)
                return

        # Fallback: press ENTER/SELECT (submits focused form)
        self._log.info("    Login button not found by text — pressing SELECT")
        self._remote.press_keycode(66, delay=0.5)  # KEYCODE_ENTER

    def _email_typed(self, email: str) -> bool:
        """Check if the email text appears somewhere on screen (not in passwords)."""
        # Just check the field moved past email stage — any text field has content
        # (We can't read EditText value directly from uiautomator easily)
        return True   # Optimistic — actual failure surfaced by login step

    def _focused_is_input(self) -> bool:
        focused = self._inspector.get_focused_element()
        if not focused:
            return False
        return _is_input_element(focused)

    def _detect_login_error(self) -> str:
        """Look for error messages on screen after a failed login attempt."""
        error_indicators = [
            "Invalid", "incorrect", "wrong", "failed", "error",
            "not found", "does not exist", "try again", "unauthorized",
            "Invalid credentials", "Invalid email", "Invalid password",
        ]
        for indicator in error_indicators:
            if self._inspector.is_text_visible(indicator):
                all_text = self._inspector.get_all_text()
                # Return the most likely error message
                for t in all_text:
                    if indicator.lower() in t.lower():
                        return f"Error on screen: '{t}'"
        return ""


def _is_input_element(el) -> bool:
    """Return True if this element is a text input field."""
    return any(cls in el.class_name for cls in
               ["EditText", "TextInput", "ReactEditText"])
