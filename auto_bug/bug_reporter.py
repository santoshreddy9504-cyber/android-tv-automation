"""
Auto Bug Report Generator — creates complete, developer-ready bug reports.

For each crash, automatically creates:
  - Title (AI-generated, clear and searchable)
  - Steps to reproduce
  - Expected vs actual behavior
  - Device info, app version, OS
  - Logcat snippet (relevant lines only)
  - Screenshot embedded
  - Video clip reference (10s before crash)
  - Memory/CPU readings at crash time
  - AI root cause and fix suggestion
  - Can export to: HTML, JSON, Markdown, GitHub Issue, Jira

Usage:
    reporter = BugReporter(adb_client)
    bug = reporter.create_from_crash(crash_event, ai_analysis)
    reporter.export_html(bug, "output/bugs/bug_001.html")
    reporter.post_github_issue(bug, token, owner, repo)
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


@dataclass
class BugReport:
    """A complete, developer-ready bug report."""
    bug_id: str
    created_at: datetime

    # Identity
    title: str = ""
    app_name: str = ""
    app_package: str = ""
    app_version: str = ""

    # Device context
    device_name: str = ""
    device_model: str = ""
    android_version: str = ""
    device_ip: str = ""

    # Bug details
    crash_type: str = ""
    severity: str = "P1"
    steps_to_reproduce: List[str] = field(default_factory=list)
    expected_behavior: str = ""
    actual_behavior: str = ""

    # Technical data
    logcat_snippet: str = ""
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    session_duration_before_crash: float = 0.0  # seconds

    # Attachments
    screenshot_paths: List[str] = field(default_factory=list)
    video_paths: List[str] = field(default_factory=list)

    # AI fields
    root_cause: str = ""
    fix_suggestion: str = ""
    fix_complexity: str = ""

    # Tracking
    tags: List[str] = field(default_factory=list)
    is_regression: bool = False

    def to_markdown(self) -> str:
        steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(self.steps_to_reproduce))
        return f"""# Bug Report: {self.title}

**ID:** {self.bug_id}
**Severity:** {self.severity}
**Date:** {self.created_at.strftime('%Y-%m-%d %H:%M')}
**App:** {self.app_name} ({self.app_package})
**Device:** {self.device_model} — Android {self.android_version}

---

## Steps to Reproduce

{steps}

## Expected Behavior

{self.expected_behavior}

## Actual Behavior

{self.actual_behavior}

---

## Root Cause (AI Analysis)

{self.root_cause}

## Suggested Fix

```
{self.fix_suggestion}
```

**Fix Complexity:** {self.fix_complexity}

---

## Technical Details

| Metric | Value |
|--------|-------|
| Memory at crash | {self.memory_mb:.0f} MB |
| CPU at crash | {self.cpu_percent:.1f}% |
| Session duration | {self.session_duration_before_crash/60:.1f} min |
| Crash type | {self.crash_type} |

## Logcat

```
{self.logcat_snippet[:2000]}
```

**Screenshots:** {len(self.screenshot_paths)} attached
**Videos:** {len(self.video_paths)} attached

**Tags:** {', '.join(self.tags)}
"""

    def to_github_issue_body(self) -> str:
        return self.to_markdown()

    def to_dict(self) -> dict:
        return {
            "bug_id": self.bug_id,
            "created_at": self.created_at.isoformat(),
            "title": self.title,
            "app_name": self.app_name,
            "severity": self.severity,
            "device_model": self.device_model,
            "android_version": self.android_version,
            "root_cause": self.root_cause,
            "fix_suggestion": self.fix_suggestion,
            "fix_complexity": self.fix_complexity,
            "memory_mb": self.memory_mb,
            "cpu_percent": self.cpu_percent,
            "logcat_snippet": self.logcat_snippet[:500],
            "tags": self.tags,
        }


class BugReporter:
    """
    Creates and exports complete bug reports from crash events.
    """

    BUG_OUTPUT_DIR = "output/bugs"

    def __init__(self, device_target: str = "", package: str = ""):
        self._target = device_target
        self._package = package
        self._bugs: List[BugReport] = []
        os.makedirs(self.BUG_OUTPUT_DIR, exist_ok=True)

    def create_from_crash(
        self,
        crash_title: str,
        crash_message: str,
        logcat_lines: List[str],
        ai_analysis=None,          # CrashAnalysis object (optional)
        memory_mb: float = 0.0,
        cpu_percent: float = 0.0,
        session_seconds: float = 0.0,
        screenshot_paths: Optional[List[str]] = None,
        video_paths: Optional[List[str]] = None,
        app_name: str = "App",
    ) -> BugReport:
        """Create a complete bug report from a crash event."""
        import uuid
        bug_id = f"BUG-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"

        bug = BugReport(
            bug_id=bug_id,
            created_at=datetime.now(),
            app_name=app_name,
            app_package=self._package,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            session_duration_before_crash=session_seconds,
            screenshot_paths=screenshot_paths or [],
            video_paths=video_paths or [],
        )

        # Get device info
        self._populate_device_info(bug)

        # App version
        bug.app_version = self._get_app_version()

        # Crash details
        bug.crash_type = crash_title
        bug.actual_behavior = f"App crashed with: {crash_message[:200]}"
        bug.expected_behavior = "App should remain stable and not crash during normal use"

        # Generate steps to reproduce from context
        bug.steps_to_reproduce = self._generate_steps(
            session_seconds, memory_mb, crash_title
        )

        # Extract relevant logcat lines
        bug.logcat_snippet = self._extract_relevant_logcat(logcat_lines, crash_title)

        # Apply AI analysis if available
        if ai_analysis:
            bug.title = ai_analysis.title or crash_title
            bug.root_cause = ai_analysis.root_cause
            bug.fix_suggestion = ai_analysis.fix_suggestion
            bug.fix_complexity = ai_analysis.fix_complexity
            bug.severity = ai_analysis.priority
            bug.expected_behavior = ai_analysis.what_happened.replace(
                "crashed", "should NOT crash"
            ) if ai_analysis.what_happened else bug.expected_behavior
        else:
            bug.title = crash_title
            bug.severity = "P0" if "fatal" in crash_title.lower() or "crash" in crash_title.lower() else "P1"

        # Tags
        bug.tags = self._generate_tags(bug)

        self._bugs.append(bug)
        logger.info(f"Bug report created: {bug.bug_id} — {bug.title}")
        return bug

    def _populate_device_info(self, bug: BugReport):
        """Fill device info from ADB."""
        if not self._target:
            bug.device_model = "Unknown Device"
            bug.android_version = "Unknown"
            return
        try:
            bug.device_model = self._shell("getprop ro.product.model")
            bug.android_version = self._shell("getprop ro.build.version.release")
            brand = self._shell("getprop ro.product.brand")
            bug.device_name = f"{brand} {bug.device_model}".strip()
            bug.device_ip = self._target.split(":")[0]
        except Exception:
            bug.device_model = "Unknown"
            bug.android_version = "Unknown"

    def _get_app_version(self) -> str:
        if not self._target or not self._package:
            return "Unknown"
        try:
            out = self._shell(f"dumpsys package {self._package} | grep versionName")
            for line in out.splitlines():
                if "versionName" in line:
                    return line.split("=")[-1].strip()
        except Exception:
            pass
        return "Unknown"

    def _shell(self, cmd: str) -> str:
        try:
            result = subprocess.run(
                ["adb", "-s", self._target, "shell", cmd],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _generate_steps(
        self, session_seconds: float, memory_mb: float, crash_type: str
    ) -> List[str]:
        """Auto-generate reproduction steps based on crash context."""
        steps = [
            f"Open {self._package or 'the app'} on Android TV",
            "Wait for app to fully load",
        ]

        if session_seconds > 60:
            steps.append(f"Use the app for approximately {session_seconds/60:.0f} minutes")

        if "playback" in crash_type.lower() or "video" in crash_type.lower():
            steps.append("Navigate to any video content")
            steps.append("Start video playback")
            steps.append("Watch for 2–5 minutes")
        elif "search" in crash_type.lower():
            steps.append("Navigate to Search section")
            steps.append("Type a search query")
        else:
            steps.append("Navigate through app sections (Home, Movies, Series)")

        if memory_mb > 300:
            steps.append(f"Note: Memory was at {memory_mb:.0f}MB before crash — may require extended use to reproduce")

        steps.append("Observe: app crashes unexpectedly")
        return steps

    def _extract_relevant_logcat(self, lines: List[str], crash_type: str) -> str:
        """Extract the most relevant logcat lines around the crash."""
        if not lines:
            return "No logcat available"

        keywords = [
            "FATAL", "Exception", "Error", "crash", "ANR",
            "died", "killed", "mqt_native_modules", "Reanimated",
            "OutOfMemory", self._package,
        ]

        relevant = []
        for line in lines:
            if any(k.lower() in line.lower() for k in keywords):
                relevant.append(line.strip())

        if relevant:
            return "\n".join(relevant[-50:])  # Last 50 relevant lines
        return "\n".join(lines[-30:])  # Last 30 lines as fallback

    def _generate_tags(self, bug: BugReport) -> List[str]:
        tags = []
        if "crash" in bug.title.lower() or "fatal" in bug.title.lower():
            tags.append("crash")
        if "memory" in bug.title.lower() or bug.memory_mb > 350:
            tags.append("memory-leak")
        if "react" in bug.root_cause.lower() or "reanimated" in bug.root_cause.lower():
            tags.append("react-native")
        if "anr" in bug.title.lower():
            tags.append("anr")
        if bug.severity == "P0":
            tags.append("critical")
            tags.append("must-fix")
        if "android-tv" in bug.device_name.lower() or not bug.device_name:
            tags.append("android-tv")
        tags.append("automated-qa")
        return list(set(tags))

    def export_html(self, bug: BugReport, output_path: Optional[str] = None) -> str:
        """Generate a standalone HTML bug report file."""
        if not output_path:
            fname = f"{bug.bug_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            output_path = os.path.join(self.BUG_OUTPUT_DIR, fname)

        severity_colors = {"P0": "#dc2626", "P1": "#ea580c", "P2": "#ca8a04"}
        s_color = severity_colors.get(bug.severity, "#6b7280")
        steps_html = "".join(
            f'<li style="margin-bottom:8px;">{s}</li>'
            for s in bug.steps_to_reproduce
        )
        screenshots_html = ""
        for sp in bug.screenshot_paths[:6]:
            if os.path.exists(sp):
                screenshots_html += (
                    f'<img src="{sp}" style="max-width:300px; border-radius:6px; margin:4px;">'
                )

        html = f"""<!DOCTYPE html>
<html>
<head>
  <title>{bug.bug_id}: {bug.title}</title>
  <style>
    body {{ background:#13131f; color:#f8f8f2; font-family:sans-serif; padding:24px; max-width:900px; margin:0 auto; }}
    h1,h2,h3 {{ color:#bd93f9; }}
    .card {{ background:#1e1e2e; border-radius:8px; padding:20px; margin:16px 0; }}
    .badge {{ display:inline-block; padding:3px 12px; border-radius:12px; font-size:13px; font-weight:bold; }}
    pre {{ background:#0d0d1a; padding:16px; border-radius:6px; overflow-x:auto; font-size:12px; color:#50fa7b; white-space:pre-wrap; }}
    table {{ width:100%; border-collapse:collapse; }}
    td,th {{ padding:10px; border-bottom:1px solid #2a2a3e; }}
    th {{ color:#6272a4; font-size:11px; text-transform:uppercase; text-align:left; }}
  </style>
</head>
<body>
  <div style="display:flex; align-items:center; gap:16px; margin-bottom:24px;">
    <span class="badge" style="background:{s_color}; color:white; font-size:16px;">{bug.severity}</span>
    <h1 style="margin:0;">{bug.bug_id}: {bug.title}</h1>
  </div>

  <div class="card">
    <table>
      <tr><th>App</th><td>{bug.app_name} ({bug.app_package})</td>
          <th>Version</th><td>{bug.app_version}</td></tr>
      <tr><th>Device</th><td>{bug.device_name or bug.device_model}</td>
          <th>Android</th><td>{bug.android_version}</td></tr>
      <tr><th>Date</th><td>{bug.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
          <th>Tags</th><td>{', '.join(f'<span class="badge" style="background:#2a2a3e; margin:2px;">{t}</span>' for t in bug.tags)}</td></tr>
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Steps to Reproduce</h2>
    <ol>{steps_html}</ol>
    <h3>Expected</h3>
    <p style="color:#50fa7b;">{bug.expected_behavior}</p>
    <h3>Actual</h3>
    <p style="color:#ff5555;">{bug.actual_behavior}</p>
  </div>

  <div class="card" style="border-left:4px solid #50fa7b;">
    <h2 style="margin-top:0; color:#50fa7b;">AI Root Cause Analysis</h2>
    <p>{bug.root_cause}</p>
    <h3>Suggested Fix ({bug.fix_complexity})</h3>
    <pre>{bug.fix_suggestion}</pre>
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Performance at Crash</h2>
    <table>
      <tr><th>Memory</th><td style="color:#ff5555;">{bug.memory_mb:.0f} MB</td></tr>
      <tr><th>CPU</th><td>{bug.cpu_percent:.1f}%</td></tr>
      <tr><th>Session Duration</th><td>{bug.session_duration_before_crash/60:.1f} minutes</td></tr>
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Logcat</h2>
    <pre>{bug.logcat_snippet[:3000]}</pre>
  </div>

  {f'<div class="card"><h2 style="margin-top:0;">Screenshots</h2>{screenshots_html}</div>' if bug.screenshot_paths else ''}
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"Bug report saved: {output_path}")
        return output_path

    def post_github_issue(
        self,
        bug: BugReport,
        token: str,
        owner: str,
        repo: str,
    ) -> Optional[str]:
        """Create a GitHub issue from this bug report. Returns issue URL."""
        try:
            import urllib.request, json
            payload = {
                "title": f"[{bug.severity}] {bug.bug_id}: {bug.title}",
                "body": bug.to_github_issue_body(),
                "labels": bug.tags,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                data=data,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                url = result.get("html_url", "")
                logger.info(f"GitHub issue created: {url}")
                return url
        except Exception as exc:
            logger.error(f"GitHub issue creation failed: {exc}")
            return None

    @property
    def all_bugs(self) -> List[BugReport]:
        return self._bugs
