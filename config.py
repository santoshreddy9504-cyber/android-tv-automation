"""
Central configuration for the Android TV Automation & Monitoring System.
Credentials and device IP are loaded from a .env file — copy
.env.example to .env and fill in your values before running.
"""

import os
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
# Device configuration
# ---------------------------------------------------------------------------
@dataclass
class DeviceConfig:
    # ADB connection — override via DEVICE_IP / ADB_PORT in .env
    device_ip: str = field(default_factory=lambda: os.getenv("DEVICE_IP", "192.168.2.29"))
    adb_port: int = field(default_factory=lambda: int(os.getenv("ADB_PORT", "5555")))
    connection_timeout: int = 30            # seconds to wait for ADB connect
    reconnect_retries: int = 5
    reconnect_delay: int = 10               # seconds between reconnect attempts

    @property
    def adb_target(self) -> str:
        return f"{self.device_ip}:{self.adb_port}"


# ---------------------------------------------------------------------------
# Login credentials
# ---------------------------------------------------------------------------
@dataclass
class LoginConfig:
    # Loaded from .env → ROD_TV_EMAIL / ROD_TV_PASSWORD
    # If the env vars are missing the fields are empty strings, which causes
    # TC000 to fail fast with a clear "credentials not configured" message.
    email:             str  = field(default_factory=lambda: os.getenv("ROD_TV_EMAIL", ""))
    password:          str  = field(default_factory=lambda: os.getenv("ROD_TV_PASSWORD", ""))
    skip_if_logged_in: bool = True        # Skip login if home is already visible
    login_timeout:     int  = 30          # Seconds to wait for home after login
    # Text labels the login screen may use (case-insensitive)
    login_screen_indicators: List[str] = field(default_factory=lambda: [
        "Sign In", "Login", "Log In", "Email", "Username",
        "Password", "Sign in to", "Enter email",
    ])
    home_indicators: List[str] = field(default_factory=lambda: [
        "Home", "Featured", "Trending", "Live", "Movies",
        "Series", "Continue Watching", "Watch Now",
    ])


# ---------------------------------------------------------------------------
# App under test
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    package_name: str = "com.webnexs.rod_tv"         # ROD TV
    launch_activity: str = ".MainActivity"           # ROD TV Main Activity
    app_name: str = "ROD TV"
    startup_wait: int = 8                            # seconds after launch
    crash_restart_enabled: bool = True
    max_crash_restarts: int = 5
    restart_cooldown: int = 15                       # seconds before restart


# ---------------------------------------------------------------------------
# Monitoring configuration
# ---------------------------------------------------------------------------
@dataclass
class MonitorConfig:
    # Session
    session_duration_hours: float = 3.0             # 0 = run indefinitely
    logcat_buffer_size: int = 10000                 # lines to keep in memory

    # Performance polling
    performance_poll_interval: int = 30             # seconds
    cpu_alert_threshold: float = 85.0              # percent
    memory_alert_threshold_mb: float = 500.0        # MB
    frame_drop_alert_threshold: float = 10.0        # percent of janky frames

    # Logcat filters (empty = capture all)
    logcat_tags: List[str] = field(default_factory=list)

    # Section names to watch for loading failures
    watched_sections: List[str] = field(default_factory=lambda: [
        "Direct section",
        "Home",
        "Continue Watching",
        "Trending",
        "My List",
        "Live TV",
    ])


# ---------------------------------------------------------------------------
# Alert / Handler configuration
# ---------------------------------------------------------------------------
@dataclass
class AlertConfig:
    # Console output
    print_alerts: bool = True
    use_colors: bool = True

    # Screenshots
    capture_screenshot_on_issue: bool = True
    screenshot_on_severities: List[str] = field(default_factory=lambda: [
        "CRITICAL", "HIGH"
    ])

    # Sound notifications (requires 'playsound' or system beep)
    sound_alerts_enabled: bool = True
    sound_on_crash: bool = True
    sound_on_critical: bool = True

    # Log files
    save_logs_on_issue: bool = True
    log_context_lines: int = 50         # lines before/after issue in saved log

    # Notification (macOS / Linux desktop notify)
    desktop_notifications: bool = True


# ---------------------------------------------------------------------------
# Dashboard configuration
# ---------------------------------------------------------------------------
@dataclass
class DashboardConfig:
    cli_dashboard_enabled: bool = True
    cli_refresh_interval: float = 2.0   # seconds

    web_dashboard_enabled: bool = True
    web_host: str = "0.0.0.0"
    web_port: int = 8080


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
@dataclass
class ReportConfig:
    generate_html_report: bool = True
    generate_json_report: bool = True
    auto_open_report: bool = True       # open HTML in browser after session


# ---------------------------------------------------------------------------
# Master config object  (import this everywhere)
# ---------------------------------------------------------------------------
@dataclass
class Config:
    device:    DeviceConfig    = field(default_factory=DeviceConfig)
    app:       AppConfig       = field(default_factory=AppConfig)
    login:     LoginConfig     = field(default_factory=LoginConfig)
    monitor:   MonitorConfig   = field(default_factory=MonitorConfig)
    alert:     AlertConfig     = field(default_factory=AlertConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    report:    ReportConfig    = field(default_factory=ReportConfig)


# Singleton instance — import and modify before calling main()
config = Config()
