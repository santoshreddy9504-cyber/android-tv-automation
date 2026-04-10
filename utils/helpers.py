"""
Utility helpers used across the project.
"""

import os
import re
import platform
import subprocess
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def safe_filename(name: str, max_len: int = 60) -> str:
    """Convert arbitrary string to a safe filename component."""
    name = re.sub(r'[^A-Za-z0-9_\-]', '_', name)
    return name[:max_len].strip("_")


def timestamp_str(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Return current timestamp as a formatted string."""
    return datetime.now().strftime(fmt)


def human_duration(seconds: float) -> str:
    """Convert seconds to 'Xh Ym Zs' string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def check_adb_installed() -> bool:
    """Return True if adb is on the PATH."""
    try:
        result = subprocess.run(
            ["adb", "version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_adb_version() -> str:
    """Return adb version string."""
    try:
        result = subprocess.run(
            ["adb", "version"],
            capture_output=True, text=True, timeout=5,
        )
        first_line = result.stdout.strip().splitlines()[0]
        return first_line
    except Exception:
        return "unknown"


def ensure_output_dirs():
    """Create output directories if they don't exist."""
    from config import SCREENSHOTS_DIR, LOGS_DIR, REPORTS_DIR
    for d in (SCREENSHOTS_DIR, LOGS_DIR, REPORTS_DIR):
        os.makedirs(d, exist_ok=True)


def bytes_to_mb(b: int) -> float:
    return b / (1024 * 1024)


def print_banner():
    """Print startup banner."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║          Android TV OTT Automation & Monitor                 ║
║          Production-grade QA Testing System                  ║
╚══════════════════════════════════════════════════════════════╝"""
    print(banner)
