"""
App Controller — manages Android app lifecycle (launch, stop, restart).
"""

import time
import logging
from typing import Optional

from config import config
from core.adb_client import ADBClient

logger = logging.getLogger(__name__)


class AppController:
    """
    Controls the OTT app under test: launch, force-stop, restart.
    Tracks crash-restart count to prevent infinite restart loops.
    """

    def __init__(self, adb: ADBClient):
        self._adb = adb
        self._package = config.app.package_name
        self._restart_count = 0
        self._last_restart_time: Optional[float] = None

    @property
    def restart_count(self) -> int:
        return self._restart_count

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def _clear_hijackers(self):
        """Force-stop common apps that background others on Android TV."""
        hijackers = [
            "com.android.vending",  # Google Play Store (Update splash screens)
            "com.google.android.gms", # Google Play Services
        ]
        for pkg in hijackers:
            try:
                self._adb.shell(f"am force-stop {pkg}")
                logger.debug(f"Cleared hijacker: {pkg}")
            except Exception:
                pass

    def launch(self) -> bool:
        """
        Launch the app. Uses monkey if no explicit activity is configured.
        Waits for startup_wait seconds after launching.
        Returns True if app is running after launch.
        """
        self._clear_hijackers()
        logger.info(f"Launching {self._package} ...")

        try:
            act = config.app.launch_activity or ".MainActivity"
            # Always use LEANBACK_LAUNCHER intent for Android TV apps
            cmd = (f"am start -a android.intent.action.MAIN "
                   f"-c android.intent.category.LEANBACK_LAUNCHER "
                   f"-n {self._package}/{act}")

            output = self._adb.shell(cmd)
            logger.debug(f"Launch output: {output}")

            logger.info(f"Waiting {config.app.startup_wait}s for app to start ...")
            time.sleep(config.app.startup_wait)

            pid = self._adb.get_app_pid(self._package)
            if pid:
                if self.is_foreground():
                    logger.info(f"App launched successfully (PID: {pid})")
                    return True
                else:
                    logger.warning(f"App running (PID: {pid}) but NOT in foreground. Attempting rescue...")
                    return self.bring_to_foreground()
            else:
                logger.warning("App launch command sent but PID not found")
                return False

        except Exception as exc:
            logger.error(f"Failed to launch app: {exc}")
            return False

    def launch_with_deeplink(self, deeplink_uri: str) -> bool:
        """Launch app via a deep link URI."""
        try:
            cmd = f"am start -a android.intent.action.VIEW -d '{deeplink_uri}'"
            output = self._adb.shell(cmd)
            logger.debug(f"Deeplink launch: {output}")
            time.sleep(config.app.startup_wait)
            return self._adb.get_app_pid(self._package) is not None
        except Exception as exc:
            logger.error(f"Deep link launch failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    def force_stop(self) -> bool:
        """Force-stop the app."""
        try:
            self._adb.shell(f"am force-stop {self._package}")
            logger.info(f"Force-stopped {self._package}")
            time.sleep(2)
            return True
        except Exception as exc:
            logger.error(f"Force-stop failed: {exc}")
            return False

    def clear_app_data(self) -> bool:
        """Clear app data and cache."""
        try:
            self._adb.shell(f"pm clear {self._package}")
            logger.info(f"Cleared data for {self._package}")
            return True
        except Exception as exc:
            logger.error(f"Clear data failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------

    def restart(self, reason: str = "unknown") -> bool:
        """
        Restart the app. Enforces max restart limits and cooldown.
        Returns True if restart succeeded.
        """
        if not config.app.crash_restart_enabled:
            logger.info("Auto-restart is disabled in config")
            return False

        if self._restart_count >= config.app.max_crash_restarts:
            logger.error(
                f"Max restart limit reached ({config.app.max_crash_restarts}). "
                "Stopping auto-restart."
            )
            return False

        # Enforce cooldown between restarts
        if self._last_restart_time:
            elapsed = time.time() - self._last_restart_time
            remaining = config.app.restart_cooldown - elapsed
            if remaining > 0:
                logger.info(f"Waiting {remaining:.1f}s before restart (cooldown) ...")
                time.sleep(remaining)

        logger.warning(f"Restarting app (reason: {reason}, attempt #{self._restart_count + 1})")

        self.force_stop()
        time.sleep(3)
        success = self.launch()

        if success:
            self._restart_count += 1
            self._last_restart_time = time.time()
            logger.info(f"App restarted successfully (total restarts: {self._restart_count})")
        else:
            logger.error("App restart failed")

        return success

    def reset_restart_count(self):
        """Reset restart counter (e.g. after a stable period)."""
        self._restart_count = 0
        logger.debug("Restart counter reset")

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._adb.get_app_pid(self._package) is not None

    def is_foreground(self) -> bool:
        return self._adb.is_app_foreground(self._package)

    def bring_to_foreground(self) -> bool:
        """Bring a backgrounded app to the foreground using monkey (safest for Android TV)."""
        try:
            act = config.app.launch_activity or ".MainActivity"
            self._adb.shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LEANBACK_LAUNCHER "
                f"-n {self._package}/{act}"
            )
            time.sleep(3)
            if self.is_foreground():
                return True
            # Second attempt: am start with LEANBACK category
            self._adb.shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LEANBACK_LAUNCHER "
                f"-p {self._package}"
            )
            time.sleep(3)
            return self.is_foreground()
        except Exception:
            return False

    def get_app_version(self) -> str:
        """Return versionName from package manager."""
        try:
            output = self._adb.shell(
                f"dumpsys package {self._package} | grep versionName"
            )
            for line in output.splitlines():
                if "versionName" in line:
                    return line.split("=")[-1].strip()
        except Exception:
            pass
        return "unknown"
