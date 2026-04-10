"""
App Inspector — mirrors Android Studio's App Inspector panel.

Combines three inspection sources into one unified snapshot:
  1. UI Hierarchy   — uiautomator dump (like Layout Inspector)
  2. App State      — dumpsys activity / meminfo / gfxinfo
  3. API Calls      — live feed from APIMonitor (like Network Inspector)

Usage (in a test scenario):
    from core.app_inspector import AppInspector
    inspector = AppInspector(adb_client, api_monitor)
    snap = inspector.snapshot()
    snap.print_tree()          # pretty-print view tree
    snap.api_table()           # print API call log
    snap.save_html("out.html") # save full inspection report
"""

import subprocess
import xml.etree.ElementTree as ET
import json
import os
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


# ── UI tree node ──────────────────────────────────────────────────────────────

@dataclass
class ViewNode:
    index:        int
    depth:        int
    class_name:   str
    resource_id:  str
    text:         str
    content_desc: str
    clickable:    bool
    focusable:    bool
    focused:      bool
    scrollable:   bool
    enabled:      bool
    bounds:       str
    children:     List["ViewNode"] = field(default_factory=list)

    @property
    def label(self) -> str:
        return (self.text or self.content_desc or
                self.resource_id.split("/")[-1] or
                self.class_name.split(".")[-1])

    @property
    def short_class(self) -> str:
        return self.class_name.split(".")[-1]

    def as_dict(self) -> dict:
        return {
            "class":       self.class_name,
            "resource_id": self.resource_id,
            "text":        self.text,
            "focused":     self.focused,
            "clickable":   self.clickable,
            "bounds":      self.bounds,
            "children":    [c.as_dict() for c in self.children],
        }


# ── Snapshot ──────────────────────────────────────────────────────────────────

@dataclass
class InspectorSnapshot:
    timestamp:    str
    screen:       str                  # current activity name
    app_state:    str                  # foreground / background / stopped
    package:      str
    pid:          int
    cpu_pct:      float
    memory_mb:    float
    total_frames: int
    janky_frames: int
    view_root:    Optional[ViewNode]   # full UI tree
    api_calls:    List[dict]           # last N api calls from APIMonitor
    background_tasks: Dict[str, list] = field(default_factory=dict)
    media_state:  str = "stopped"
    raw_xml:      str = ""

    # ── Tree print ────────────────────────────────────────────────────────

    def print_tree(self, max_depth: int = 6):
        print(f"\n{'─'*60}")
        print(f"  📱 App Inspector Snapshot — {self.timestamp}")
        print(f"  Screen : {self.screen}")
        print(f"  State  : {self.app_state}   PID:{self.pid}")
        print(f"  CPU    : {self.cpu_pct:.1f}%   RAM: {self.memory_mb:.0f} MB")
        print(f"{'─'*60}")
        if self.view_root:
            self._print_node(self.view_root, 0, max_depth)
        else:
            print("  (no UI hierarchy available)")
        print(f"{'─'*60}\n")

    def _print_node(self, node: ViewNode, depth: int, max_depth: int):
        if depth > max_depth:
            return
        indent = "  " * depth
        focus  = "► " if node.focused else "  "
        label  = f'"{node.text}"' if node.text else f"[{node.short_class}]"
        rid    = f" @{node.resource_id.split('/')[-1]}" if node.resource_id else ""
        flags  = []
        if node.clickable:  flags.append("click")
        if node.scrollable: flags.append("scroll")
        flag_str = f" ({','.join(flags)})" if flags else ""
        print(f"{indent}{focus}{label}{rid}{flag_str}  {node.bounds}")
        for child in node.children:
            self._print_node(child, depth + 1, max_depth)

    # ── API table ─────────────────────────────────────────────────────────

    def api_table(self):
        print(f"\n{'─'*80}")
        print(f"  🌐 API Calls ({len(self.api_calls)} captured)")
        print(f"{'─'*80}")
        print(f"  {'Method':<7} {'Status':<7} {'ms':>6}  URL")
        print(f"  {'─'*7} {'─'*7} {'─'*6}  {'─'*50}")
        for c in self.api_calls[-30:]:
            ms  = f"{c.get('response_ms', 0)}"
            code = c.get('status_code', 0) or c.get('error', 'ERR')
            url  = c.get('url', '')[-60:]
            print(f"  {c.get('method','GET'):<7} {str(code):<7} {ms:>6}ms  {url}")
        print(f"{'─'*80}\n")

    # ── Save HTML ─────────────────────────────────────────────────────────

    def save_html(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        html = self._build_html()
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def _build_html(self) -> str:
        tree_html = self._node_to_html(self.view_root, 0) if self.view_root else "<p>No UI data</p>"
        api_rows  = ""
        for c in self.api_calls[-100:]:
            code  = c.get("status_code", 0)
            error = c.get("error", "")
            ms    = c.get("response_ms", 0)
            url   = c.get("url", "")
            method= c.get("method", "GET")
            color = ("#22cc66" if 200 <= code < 300
                     else "#ff4444" if code >= 400 or error
                     else "#ffaa00" if ms > 3000
                     else "#7b9fff")
            status = error[:30] if error else (str(code) if code else "—")
            slow_warn = " ⚠️" if ms > 3000 else ""
            api_rows += f"""
<tr>
  <td style="color:#7b9fff;font-weight:600">{method}</td>
  <td style="color:{color};font-weight:700">{status}</td>
  <td style="color:{'#ff9944' if ms > 3000 else '#888'}">{ms}ms{slow_warn}</td>
  <td style="color:#ccd;font-size:.82em;word-break:break-all">{url}</td>
  <td style="color:#555;font-size:.75em">{c.get('source','')}</td>
</tr>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>App Inspector — {self.package} — {self.timestamp}</title>
<style>
  * {{box-sizing:border-box;margin:0;padding:0}}
  body {{font-family:'Segoe UI',system-ui,sans-serif;background:#080a12;color:#ccd;font-size:13px}}
  h2 {{font-size:1.1em;color:#8aabff;margin-bottom:8px}}
  .header {{background:#0d1128;padding:22px 36px;border-bottom:2px solid #1e2550}}
  .header h1 {{font-size:1.4em;color:#8aabff}}
  .meta {{display:flex;gap:24px;margin-top:10px;flex-wrap:wrap}}
  .meta-item {{font-size:.82em;color:#3a4e88}} .meta-item strong {{color:#7b9fff}}
  .container {{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:28px 36px;max-width:1600px}}
  .panel {{background:#0e1020;border-radius:12px;padding:18px;overflow:auto;max-height:82vh}}
  .panel.full {{grid-column:1/-1}}
  /* Tree */
  .tree-node {{padding:3px 0 3px 18px;border-left:1px solid #1e2240;margin-left:4px;cursor:pointer}}
  .tree-node:hover {{background:#141828}}
  .node-label {{display:flex;gap:8px;align-items:center}}
  .node-class {{color:#5566aa;font-size:.75em}}
  .node-text {{color:#eef;font-weight:500}}
  .node-id {{color:#3a7acc;font-size:.75em}}
  .node-focused {{color:#ffcc00;margin-right:4px}}
  .flag {{background:#1a2040;color:#5577bb;padding:1px 6px;border-radius:3px;font-size:.7em}}
  /* API table */
  table {{width:100%;border-collapse:collapse}}
  th {{background:#0b0d1a;padding:8px 12px;text-align:left;color:#3a4e88;font-size:.7em;
       text-transform:uppercase;letter-spacing:.8px}}
  td {{padding:7px 12px;border-top:1px solid #141828;vertical-align:top}}
  tr:hover td {{background:#111428}}
  /* Metric cards */
  .metrics {{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}}
  .metric {{background:#12152a;border-radius:8px;padding:12px 16px;min-width:100px;
            border-top:3px solid #2a3060}}
  .metric-val {{font-size:1.6em;font-weight:700;color:#fff}}
  .metric-lbl {{color:#3a4e88;font-size:.68em;text-transform:uppercase;letter-spacing:.6px;margin-top:4px}}
</style>
</head>
<body>
<div class="header">
  <h1>📱 App Inspector — {self.package}</h1>
  <div class="meta">
    <div class="meta-item">Snapshot: <strong>{self.timestamp}</strong></div>
    <div class="meta-item">Screen: <strong>{self.screen}</strong></div>
    <div class="meta-item">State: <strong>{self.app_state}</strong></div>
    <div class="meta-item">PID: <strong>{self.pid}</strong></div>
    <div class="meta-item">Playback: <strong style="color:{'#22cc66' if self.media_state=='playing' else '#5a648a'}">{self.media_state.upper()}</strong></div>
  </div>
  <div class="metrics">
    <div class="metric" style="border-color:#4a6fff">
      <div class="metric-val">{self.cpu_pct:.1f}%</div><div class="metric-lbl">CPU</div>
    </div>
    <div class="metric" style="border-color:#22cc66">
      <div class="metric-val">{self.memory_mb:.0f}</div><div class="metric-lbl">RAM (MB)</div>
    </div>
    <div class="metric" style="border-color:#ffaa00">
      <div class="metric-val">{self.janky_frames}</div><div class="metric-lbl">Janky Frames</div>
    </div>
    <div class="metric" style="border-color:#7b9fff">
      <div class="metric-val">{len(self.api_calls)}</div><div class="metric-lbl">API Calls</div>
    </div>
  </div>
</div>

<div class="container">
  <div class="panel">
    <h2>🖼 Layout Inspector (View Hierarchy)</h2>
    <div style="margin-top:12px;font-family:monospace;font-size:.82em">
      {tree_html}
    </div>
  </div>

  <div class="panel">
    <h2>🌐 Network Inspector (API Calls)</h2>
    <table style="margin-top:12px">
      <thead>
        <tr>
          <th>Method</th><th>Status</th><th>Time</th><th>URL</th><th>Source</th>
        </tr>
      </thead>
      <tbody>
        {api_rows if api_rows else '<tr><td colspan="5" style="color:#555;padding:16px">No API calls captured yet</td></tr>'}
      </tbody>
    </table>
  </div>
</div>
</body></html>"""

    def _node_to_html(self, node: ViewNode, depth: int) -> str:
        if depth > 10:
            return ""
        pad   = depth * 16
        focus = '<span class="node-focused">►</span>' if node.focused else ""
        text  = f'<span class="node-text">"{node.text}"</span>' if node.text else ""
        rid   = (f'<span class="node-id">@{node.resource_id.split("/")[-1]}</span>'
                 if node.resource_id else "")
        flags = "".join(
            f'<span class="flag">{f}</span>'
            for f in (["click"] if node.clickable else []) +
                     (["focus"] if node.focusable else []) +
                     (["scroll"] if node.scrollable else [])
        )
        cls   = f'<span class="node-class">{node.short_class}</span>'
        children_html = "".join(self._node_to_html(c, depth + 1) for c in node.children)
        return f"""
<div class="tree-node" style="padding-left:{pad+18}px">
  <div class="node-label">{focus}{cls}{text}{rid}{flags}</div>
  {children_html}
</div>"""


# ── Main Inspector class ──────────────────────────────────────────────────────

class AppInspector:
    """
    One-shot or continuous app inspection.
    Pass your ADBClient and (optionally) an APIMonitor instance.
    """

    def __init__(self, adb_client, api_monitor=None):
        self._adb = adb_client
        self._api = api_monitor

    def snapshot(self, package: str = None) -> InspectorSnapshot:
        """Capture a full inspection snapshot right now."""
        from config import config
        pkg = package or config.app.package_name
        target = config.device.adb_target

        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pid   = self._adb.get_app_pid(pkg) or 0
        cpu   = self._adb.get_cpu_usage(pkg)
        mem, _ = self._adb.get_memory_usage(pkg)
        gfx   = self._adb.get_gfxinfo(pkg)
        screen = self._get_current_activity(target)
        state = "foreground" if self._adb.is_app_foreground(pkg) else "background"
        xml, root = self._get_ui_tree(target)
        api_calls = [vars(c) if hasattr(c, '__dict__') else c
                     for c in (self._api.snapshot() if self._api else [])]

        return InspectorSnapshot(
            timestamp=ts,
            screen=screen,
            app_state=state,
            package=pkg,
            pid=pid,
            cpu_pct=cpu,
            memory_mb=mem,
            total_frames=gfx.get("total_frames", 0),
            janky_frames=gfx.get("janky_frames", 0),
            view_root=root,
            api_calls=api_calls,
            background_tasks=self._get_background_tasks(pkg),
            media_state=self._get_media_info(pkg),
            raw_xml=xml or "",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_current_activity(self, target: str) -> str:
        try:
            out = self._adb.shell(
                "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'"
            )
            for line in out.splitlines():
                if "mCurrentFocus" in line or "mFocusedApp" in line:
                    parts = line.strip().split()
                    for p in parts:
                        if "/" in p and "." in p:
                            return p.strip("}")
        except Exception:
            pass
        return "unknown"

    def _get_ui_tree(self, target: str):
        """Dump UIAutomator XML and parse into ViewNode tree."""
        try:
            subprocess.run(
                ["adb", "-s", target, "shell", "uiautomator dump /sdcard/inspector_dump.xml"],
                capture_output=True, timeout=15,
            )
            result = subprocess.run(
                ["adb", "-s", target, "shell", "cat /sdcard/inspector_dump.xml"],
                capture_output=True, text=True, timeout=10,
            )
            xml = result.stdout.strip()
            if xml and "<hierarchy" in xml:
                root_et = ET.fromstring(xml)
                return xml, self._parse_node(root_et.find(".//node"), 0)
        except Exception as exc:
            logger.debug(f"UI tree dump failed: {exc}")
        return None, None

    def _parse_node(self, node_et: Optional[ET.Element], depth: int) -> Optional[ViewNode]:
        if node_et is None:
            return None
        vn = ViewNode(
            index=int(node_et.get("index", 0)),
            depth=depth,
            class_name=node_et.get("class", ""),
            resource_id=node_et.get("resource-id", ""),
            text=node_et.get("text", ""),
            content_desc=node_et.get("content-desc", ""),
            clickable=node_et.get("clickable") == "true",
            focusable=node_et.get("focusable") == "true",
            focused=node_et.get("focused") == "true",
            scrollable=node_et.get("scrollable") == "true",
            enabled=node_et.get("enabled") == "true",
            bounds=node_et.get("bounds", ""),
        )
        for child_et in node_et.findall("node"):
            child = self._parse_node(child_et, depth + 1)
            if child:
                vn.children.append(child)
        return vn

    def _get_background_tasks(self, pkg: str) -> Dict[str, list]:
        """Inspector-style dump of pending Jobs and Alarms."""
        tasks = {"jobs": [], "alarms": []}
        try:
            # Jobs
            jobs_out = self._adb.shell(f"dumpsys jobscheduler | grep {pkg}")
            tasks["jobs"] = [line.strip() for line in jobs_out.splitlines() if line.strip()]
            # Alarms
            alarms_out = self._adb.shell(f"dumpsys alarm | grep {pkg}")
            tasks["alarms"] = [line.strip() for line in alarms_out.splitlines() if line.strip()]
        except Exception:
            pass
        return tasks

    def _get_media_info(self, pkg: str) -> str:
        """Verify if app is sending MediaSession signals to the OS."""
        try:
            out = self._adb.shell("dumpsys media_session | grep -i state")
            if "state=3" in out or "playing" in out.lower():
                return "playing"
            if "state=2" in out or "paused" in out.lower():
                return "paused"
        except Exception:
            pass
        return "inactive"
