"""
Notification System — Real-time alerts to Slack, Email, and desktop.

Sends crash alerts, predictions, and session summaries to:
  - Slack (webhook)
  - Email (SMTP)
  - macOS desktop notification
  - WhatsApp (via Twilio, optional)

Configure in config.py or pass directly to NotificationManager.
"""

import logging
import os
import smtplib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NotificationConfig:
    """All notification channel configuration."""
    # Slack
    slack_webhook_url: str = ""
    slack_channel: str = "#qa-alerts"
    slack_username: str = "QA Bot"

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""          # Use app password for Gmail
    email_from: str = ""
    email_to: List[str] = field(default_factory=list)

    # Desktop
    desktop_notifications: bool = True

    # Thresholds
    notify_on_crash: bool = True
    notify_on_prediction: bool = True
    notify_on_session_end: bool = True
    min_priority: str = "P1"        # Only notify P0 and P1


@dataclass
class Notification:
    """A notification to be sent."""
    title: str
    message: str
    level: str = "info"             # info | warning | critical
    priority: str = "P1"
    timestamp: datetime = field(default_factory=datetime.now)
    app_name: str = ""
    device_name: str = ""
    screenshot_path: Optional[str] = None

    def slack_payload(self) -> dict:
        colors = {"info": "#36a64f", "warning": "#ff9800", "critical": "#dc2626"}
        color = colors.get(self.level, "#36a64f")
        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(self.level, "•")

        return {
            "username": "QA Automation Bot",
            "icon_emoji": ":robot_face:",
            "attachments": [{
                "color": color,
                "title": f"{icon} {self.title}",
                "text": self.message,
                "fields": [
                    {"title": "App", "value": self.app_name, "short": True},
                    {"title": "Device", "value": self.device_name, "short": True},
                    {"title": "Priority", "value": self.priority, "short": True},
                    {"title": "Time", "value": self.timestamp.strftime('%H:%M:%S'), "short": True},
                ],
                "footer": "Android TV QA Automation",
                "ts": int(self.timestamp.timestamp()),
            }],
        }


class SlackNotifier:
    """Sends notifications to a Slack channel via webhook."""

    def __init__(self, webhook_url: str):
        self._url = webhook_url
        self._enabled = bool(webhook_url)

    def send(self, notification: Notification) -> bool:
        if not self._enabled:
            return False
        try:
            import urllib.request
            import json
            payload = json.dumps(notification.slack_payload()).encode("utf-8")
            req = urllib.request.Request(
                self._url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.error(f"Slack notification failed: {exc}")
            return False

    def send_text(self, text: str) -> bool:
        if not self._enabled:
            return False
        try:
            import urllib.request, json
            payload = json.dumps({"text": text}).encode("utf-8")
            req = urllib.request.Request(
                self._url, data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.error(f"Slack text notification failed: {exc}")
            return False


class EmailNotifier:
    """Sends email notifications via SMTP."""

    def __init__(self, config: NotificationConfig):
        self._config = config
        self._enabled = bool(config.smtp_user and config.smtp_password and config.email_to)

    def send(self, notification: Notification) -> bool:
        if not self._enabled:
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[QA Alert] {notification.title}"
            msg["From"] = self._config.email_from or self._config.smtp_user
            msg["To"] = ", ".join(self._config.email_to)

            html_body = f"""
            <html><body style="font-family:sans-serif; background:#f5f5f5; padding:20px;">
              <div style="background:white; border-radius:8px; padding:24px; max-width:600px; margin:0 auto;">
                <h2 style="color:#dc2626; margin-top:0;">🚨 QA Alert: {notification.title}</h2>
                <p style="color:#333;">{notification.message}</p>
                <table style="border-collapse:collapse; width:100%; margin-top:16px;">
                  <tr><td style="padding:8px; background:#f9f9f9; font-weight:bold;">App</td>
                      <td style="padding:8px;">{notification.app_name}</td></tr>
                  <tr><td style="padding:8px; background:#f9f9f9; font-weight:bold;">Device</td>
                      <td style="padding:8px;">{notification.device_name}</td></tr>
                  <tr><td style="padding:8px; background:#f9f9f9; font-weight:bold;">Priority</td>
                      <td style="padding:8px; color:{'#dc2626' if notification.priority == 'P0' else '#ea580c'};">
                        {notification.priority}</td></tr>
                  <tr><td style="padding:8px; background:#f9f9f9; font-weight:bold;">Time</td>
                      <td style="padding:8px;">{notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
                </table>
                <hr style="border:none; border-top:1px solid #eee; margin:20px 0;">
                <p style="color:#999; font-size:12px;">Sent by Android TV QA Automation System</p>
              </div>
            </body></html>
            """

            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port) as server:
                server.starttls()
                server.login(self._config.smtp_user, self._config.smtp_password)
                server.sendmail(
                    msg["From"],
                    self._config.email_to,
                    msg.as_string(),
                )
            logger.info(f"Email sent: {notification.title} → {self._config.email_to}")
            return True

        except Exception as exc:
            logger.error(f"Email notification failed: {exc}")
            return False

    def send_report(self, subject: str, html_content: str) -> bool:
        """Send a full HTML report via email."""
        if not self._enabled:
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._config.email_from or self._config.smtp_user
            msg["To"] = ", ".join(self._config.email_to)
            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port) as server:
                server.starttls()
                server.login(self._config.smtp_user, self._config.smtp_password)
                server.sendmail(msg["From"], self._config.email_to, msg.as_string())
            logger.info(f"Report email sent: {subject}")
            return True
        except Exception as exc:
            logger.error(f"Report email failed: {exc}")
            return False


class DesktopNotifier:
    """macOS / Linux desktop notifications."""

    def send(self, title: str, message: str) -> bool:
        import platform
        try:
            if platform.system() == "Darwin":
                import subprocess
                msg_escaped = message.replace('"', '\\"')[:100]
                title_escaped = title.replace('"', '\\"')
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{msg_escaped}" with title "{title_escaped}"'
                ], capture_output=True, timeout=3)
                return True
            elif platform.system() == "Linux":
                import subprocess
                subprocess.run(
                    ["notify-send", title, message[:100]],
                    capture_output=True, timeout=3,
                )
                return True
        except Exception as exc:
            logger.debug(f"Desktop notification failed: {exc}")
        return False


class NotificationManager:
    """
    Central notification coordinator.
    Routes alerts to all configured channels.

    Usage:
        nm = NotificationManager(config)
        nm.crash_detected("SouthStream crashed", "mqt_native_modules error",
                           app="SouthStream", device="Android TV")
        nm.prediction_warning("Crash in 3 min", "Memory 390MB → 420MB threshold")
        nm.session_complete(summary_html)
    """

    def __init__(self, config: Optional[NotificationConfig] = None):
        self._config = config or NotificationConfig()
        self._slack = SlackNotifier(self._config.slack_webhook_url)
        self._email = EmailNotifier(self._config)
        self._desktop = DesktopNotifier()
        self._queue: list = []
        self._lock = threading.Lock()

    def crash_detected(
        self,
        title: str,
        message: str,
        app: str = "",
        device: str = "",
        priority: str = "P0",
    ):
        """Send crash notification to all channels."""
        notif = Notification(
            title=title, message=message, level="critical",
            priority=priority, app_name=app, device_name=device,
        )
        self._send_all(notif)

    def prediction_warning(
        self,
        title: str,
        message: str,
        app: str = "",
        device: str = "",
    ):
        """Send predictive crash warning."""
        if not self._config.notify_on_prediction:
            return
        notif = Notification(
            title=title, message=message, level="warning",
            priority="P1", app_name=app, device_name=device,
        )
        self._send_all(notif)

    def session_complete(self, subject: str, html_report: str):
        """Email the full session report."""
        if self._config.notify_on_session_end:
            threading.Thread(
                target=self._email.send_report,
                args=(subject, html_report),
                daemon=True,
            ).start()

    def info(self, title: str, message: str, app: str = "", device: str = ""):
        notif = Notification(
            title=title, message=message, level="info",
            priority="P2", app_name=app, device_name=device,
        )
        self._send_all(notif)

    def _send_all(self, notif: Notification):
        """Fan-out notification to all channels in background threads."""
        # Desktop — synchronous (fast)
        if self._config.desktop_notifications:
            self._desktop.send(notif.title, notif.message)

        # Slack — async
        threading.Thread(
            target=self._slack.send, args=(notif,), daemon=True
        ).start()

        # Email — async
        threading.Thread(
            target=self._email.send, args=(notif,), daemon=True
        ).start()

        logger.info(f"Notification sent: [{notif.level.upper()}] {notif.title}")
