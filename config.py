"""
Central configuration for the Android TV Automation & Monitoring System.

Multi-client support
────────────────────
Set CLIENT_CONFIG in .env (or as an environment variable) to the path of a
JSON file that describes the app under test.  Example client configs live in
the clients/ directory.  Copy clients/template.json to clients/myapp.json,
fill it in, then set CLIENT_CONFIG=clients/myapp.json in your .env.

Login credentials and device IP are loaded from .env — copy .env.example
to .env and fill in your values before running.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import List

# Load .env file if present (silently ignored if missing or dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — fall back to plain env vars / defaults


# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, "screenshots")
LOGS_DIR = os.path.join(OUTPUT_DIR, "logs")
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")


# ---------------------------------------------------------------------------
# Client configuration  (loaded from JSON — one file per app under test)
# ---------------------------------------------------------------------------
@dataclass
class ClientConfig:
    """
    All app-specific settings for the client under test.
    Values come from a JSON file; set CLIENT_CONFIG=clients/myapp.json in .env.

    Sidebar items are listed top-to-bottom with their tap coordinates.
    Use the `sidebar_item(label)` helper to look up a specific entry.
    """
    app_name:                str        = "App Under Test"
    package_name:            str        = ""
    launch_activity:         str        = ".MainActivity"
    # UI text that confirms the home screen is visible
    home_indicators:         List[str]  = field(default_factory=list)
    # UI text that indicates the login screen
    login_screen_indicators: List[str]  = field(default_factory=lambda: [
        "Sign In", "Login", "Log In", "Email", "Username", "Password",
    ])
    # Texts shown in the "exit / quit" confirmation dialog
    exit_dialog_texts:       List[str]  = field(default_factory=lambda: [
        "Confirm Exit", "Are you sure you want to exit",
    ])
    # Generic content texts that confirm content is loaded
    content_indicators:      List[str]  = field(default_factory=lambda: [
        "Watch Now", "Play", "Resume", "Featured", "Trending",
        "Live", "Movies", "Series",
    ])
    # X coordinate of the navigation sidebar column
    sidebar_x:               int        = 77
    # List of sidebar items: [{label, y, indicators}]
    sidebar_items:           List[dict] = field(default_factory=list)

    def sidebar_item(self, label: str) -> dict:
        """Return the sidebar item dict for the given label, or {}."""
        for item in self.sidebar_items:
            if item.get("label") == label:
                return item
        return {}

    def sidebar_y(self, label: str) -> int:
        """Return the Y coordinate of a sidebar item (0 if not found)."""
        return self.sidebar_item(label).get("y", 0)


def _load_client_config() -> ClientConfig:
    """
    Load a ClientConfig from the JSON file pointed to by CLIENT_CONFIG.
    Falls back to clients/rod_tv.json, then to empty defaults.
    """
    path = os.getenv("CLIENT_CONFIG", "clients/rod_tv.json")
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)

    if not os.path.exists(path):
        print(
            f"[config] WARNING: CLIENT_CONFIG not found: {path}\n"
            f"         Copy clients/template.json to clients/myapp.json, "
            f"fill it in, then set CLIENT_CONFIG=clients/myapp.json in .env",
            file=sys.stderr,
        )
        return ClientConfig()

    with open(path) as fh:
        data = json.load(fh)

    known = ClientConfig.__dataclass_fields__.keys()
    return ClientConfig(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Device configuration
# ---------------------------------------------------------------------------
@dataclass
class DeviceConfig:
    # Override via DEVICE_IP / ADB_PORT in .env
    device_ip: str = field(default_factory=lambda: os.getenv("DEVICE_IP", "192.168.2.29"))
    adb_port:  int = field(default_factory=lambda: int(os.getenv("ADB_PORT", "5555")))
    connection_timeout: int = 30   # seconds to wait for ADB connect
    reconnect_retries:  int = 5
    reconnect_delay:    int = 10   # seconds between reconnect attempts

    @property
    def adb_target(self) -> str:
        return f"{self.device_ip}:{self.adb_port}"


# ---------------------------------------------------------------------------
# Login credentials
# ---------------------------------------------------------------------------
@dataclass
class LoginConfig:
    # Loaded from .env → LOGIN_EMAIL / LOGIN_PASSWORD
    # If env vars are missing the fields are empty strings, which causes
    # TC000 to fail fast with a clear "credentials not configured" message.
    email:             str  = field(default_factory=lambda: os.getenv("LOGIN_EMAIL", ""))
    password:          str  = field(default_factory=lambda: os.getenv("LOGIN_PASSWORD", ""))
    skip_if_logged_in: bool = True   # Skip login step if home is already visible
    login_timeout:     int  = 30     # Seconds to wait for home screen after login


# ---------------------------------------------------------------------------
# App / framework settings  (not client-specific — use ClientConfig for those)
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    # These are populated from ClientConfig after load (see bottom of file).
    # They can also be overridden at runtime via CLI args in run_auto_test.py.
    package_name:    str  = ""
    launch_activity: str  = ".MainActivity"
    app_name:        str  = "App Under Test"

    startup_wait:          int  = 8     # seconds after launch before interacting
    crash_restart_enabled: bool = True
    max_crash_restarts:    int  = 5
    restart_cooldown:      int  = 15    # seconds before attempting restart


# ---------------------------------------------------------------------------
# Monitoring configuration
# ---------------------------------------------------------------------------
@dataclass
class MonitorConfig:
    session_duration_hours:    float     = 3.0    # 0 = run indefinitely
    logcat_buffer_size:        int       = 10000  # lines to keep in memory
    performance_poll_interval: int       = 30     # seconds
    cpu_alert_threshold:       float     = 85.0   # percent
    memory_alert_threshold_mb: float     = 500.0  # MB
    frame_drop_alert_threshold: float    = 10.0   # percent of janky frames
    logcat_tags:               List[str] = field(default_factory=list)
    watched_sections:          List[str] = field(default_factory=lambda: [
        "Home", "Continue Watching", "Trending", "My List", "Live TV",
    ])


# ---------------------------------------------------------------------------
# Alert / Handler configuration
# ---------------------------------------------------------------------------
@dataclass
class AlertConfig:
    print_alerts:                 bool      = True
    use_colors:                   bool      = True
    capture_screenshot_on_issue:  bool      = True
    screenshot_on_severities:     List[str] = field(default_factory=lambda: ["CRITICAL", "HIGH"])
    sound_alerts_enabled:         bool      = True
    sound_on_crash:               bool      = True
    sound_on_critical:            bool      = True
    save_logs_on_issue:           bool      = True
    log_context_lines:            int       = 50
    desktop_notifications:        bool      = True


# ---------------------------------------------------------------------------
# Dashboard configuration
# ---------------------------------------------------------------------------
@dataclass
class DashboardConfig:
    cli_dashboard_enabled: bool  = True
    cli_refresh_interval:  float = 2.0
    web_dashboard_enabled: bool  = True
    web_host:              str   = "0.0.0.0"
    web_port:              int   = 8080


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
@dataclass
class ReportConfig:
    generate_html_report: bool = True
    generate_json_report: bool = True
    auto_open_report:     bool = True


# ---------------------------------------------------------------------------
# Master config object  (import this everywhere)
# ---------------------------------------------------------------------------
@dataclass
class Config:
    client:    ClientConfig    = field(default_factory=_load_client_config)
    device:    DeviceConfig    = field(default_factory=DeviceConfig)
    app:       AppConfig       = field(default_factory=AppConfig)
    login:     LoginConfig     = field(default_factory=LoginConfig)
    monitor:   MonitorConfig   = field(default_factory=MonitorConfig)
    alert:     AlertConfig     = field(default_factory=AlertConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    report:    ReportConfig    = field(default_factory=ReportConfig)


# Singleton — import and use everywhere.
config = Config()

# Populate AppConfig from ClientConfig (client JSON is the source of truth).
# CLI args in run_auto_test.py can still override these after import.
if config.client.package_name:
    config.app.package_name    = config.client.package_name
if config.client.launch_activity:
    config.app.launch_activity = config.client.launch_activity
if config.client.app_name:
    config.app.app_name        = config.client.app_name
