"""
Report Handler — generates HTML and JSON summary reports after a session.
"""

import json
import os
import webbrowser
import logging
from datetime import datetime

from config import config, REPORTS_DIR
from models.events import SessionStats

logger = logging.getLogger(__name__)


class ReportHandler:
    """
    Generates a rich HTML report and/or JSON report from session statistics.
    Called at the end of a monitoring session.
    """

    def __init__(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)

    def generate(self, stats: SessionStats) -> str:
        """Generate all configured reports. Returns HTML report path."""
        html_path = ""

        if config.report.generate_json_report:
            self._write_json(stats)

        if config.report.generate_html_report:
            html_path = self._write_html(stats)
            if config.report.auto_open_report and html_path:
                try:
                    webbrowser.open(f"file://{html_path}")
                except Exception:
                    pass

        return html_path

    # ------------------------------------------------------------------
    # JSON report
    # ------------------------------------------------------------------

    def _write_json(self, stats: SessionStats) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REPORTS_DIR, f"report_{stats.session_id}_{ts}.json")

        data = stats.to_dict()
        data["events"] = stats.all_events

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"JSON report saved: {path}")
        return path

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    def _write_html(self, stats: SessionStats) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REPORTS_DIR, f"report_{stats.session_id}_{ts}.html")

        duration_m = stats.duration_seconds / 60
        categories = stats.issues_by_category
        severities = stats.issues_by_severity

        # Colour map for categories
        cat_colors = {
            "CRASH": "#ff4d4d",
            "NETWORK": "#ff9933",
            "PLAYBACK": "#9966ff",
            "UI": "#33aaff",
            "PERFORMANCE": "#ffcc00",
            "SYSTEM": "#66cc66",
        }
        sev_colors = {
            "CRITICAL": "#ff2222",
            "HIGH":     "#ff9900",
            "MEDIUM":   "#ffdd00",
            "LOW":      "#44aaff",
            "INFO":     "#aaaaaa",
        }

        def badge(text, color):
            return (
                f'<span style="background:{color};color:#fff;padding:2px 8px;'
                f'border-radius:4px;font-size:0.85em;font-weight:bold">{text}</span>'
            )

        # Build events table rows
        rows = ""
        for evt in stats.all_events:
            cat = evt.get("category", "")
            sev = evt.get("severity", "")
            cat_color = cat_colors.get(cat, "#888")
            sev_color = sev_colors.get(sev, "#888")
            ts_str = evt.get("timestamp", "")[:19].replace("T", " ")
            rows += (
                f"<tr>"
                f"<td>{ts_str}</td>"
                f"<td>{badge(cat, cat_color)}</td>"
                f"<td>{badge(sev, sev_color)}</td>"
                f"<td><strong>{evt.get('title','')}</strong></td>"
                f"<td style='max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>"
                f"{evt.get('message','')[:200]}</td>"
                f"</tr>\n"
            )

        # Category breakdown cards
        category_cards = ""
        for cat, count in categories.items():
            color = cat_colors.get(cat, "#888")
            category_cards += (
                f'<div class="metric-card" style="border-left:4px solid {color}">'
                f'<div class="metric-value">{count}</div>'
                f'<div class="metric-label">{cat}</div>'
                f'</div>\n'
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Android TV Monitoring Report — {stats.session_id}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f1117; color: #e0e0e0; }}
  header {{ background: linear-gradient(135deg,#1a1d2e,#252840); padding: 30px 40px; border-bottom: 2px solid #3a3f60; }}
  header h1 {{ font-size: 1.8em; color: #7b9fff; }}
  header p {{ color: #8888aa; margin-top: 6px; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 30px 40px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fill,minmax(160px,1fr)); gap: 16px; margin: 24px 0; }}
  .metric-card {{ background: #1a1d2e; border-radius: 10px; padding: 20px 16px; border-left: 4px solid #4a6fff; }}
  .metric-value {{ font-size: 2em; font-weight: bold; color: #fff; }}
  .metric-label {{ color: #8888aa; font-size: 0.85em; margin-top: 4px; text-transform: uppercase; }}
  h2 {{ color: #7b9fff; margin: 28px 0 14px; font-size: 1.2em; }}
  table {{ width: 100%; border-collapse: collapse; background: #1a1d2e; border-radius: 10px; overflow: hidden; }}
  th {{ background: #252840; padding: 12px 14px; text-align: left; color: #8888aa; font-size: 0.8em; text-transform: uppercase; }}
  td {{ padding: 10px 14px; border-top: 1px solid #252840; font-size: 0.9em; vertical-align: middle; }}
  tr:hover td {{ background: #1e2235; }}
  .no-issues {{ text-align: center; color: #44aa66; padding: 40px; font-size: 1.2em; }}
  footer {{ text-align: center; color: #555; padding: 30px; font-size: 0.8em; }}
</style>
</head>
<body>
<header>
  <h1>📊 Android TV Monitoring Report</h1>
  <p>Session ID: {stats.session_id} &nbsp;|&nbsp;
     Started: {stats.start_time.strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp;
     Duration: {duration_m:.1f} min &nbsp;|&nbsp;
     App: {config.app.package_name}</p>
</header>
<div class="container">

  <h2>Session Summary</h2>
  <div class="summary-grid">
    <div class="metric-card" style="border-left:4px solid #ff4d4d">
      <div class="metric-value">{stats.total_issues}</div>
      <div class="metric-label">Total Issues</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #ff2222">
      <div class="metric-value">{stats.crash_count}</div>
      <div class="metric-label">Crashes</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #66aaff">
      <div class="metric-value">{stats.restart_count}</div>
      <div class="metric-label">Auto Restarts</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #ffcc00">
      <div class="metric-value">{stats.avg_cpu:.1f}%</div>
      <div class="metric-label">Avg CPU</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #ff9900">
      <div class="metric-value">{stats.peak_cpu:.1f}%</div>
      <div class="metric-label">Peak CPU</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #44cc88">
      <div class="metric-value">{stats.avg_memory_mb:.0f}</div>
      <div class="metric-label">Avg Mem (MB)</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #ff6633">
      <div class="metric-value">{stats.peak_memory_mb:.0f}</div>
      <div class="metric-label">Peak Mem (MB)</div>
    </div>
    <div class="metric-card" style="border-left:4px solid #aaaaaa">
      <div class="metric-value">{duration_m:.1f}</div>
      <div class="metric-label">Duration (min)</div>
    </div>
  </div>

  <h2>Issues by Category</h2>
  <div class="summary-grid">
    {category_cards if category_cards else '<p style="color:#8888aa">No issues detected.</p>'}
  </div>

  <h2>Issue Log</h2>
  {f'''<table>
    <thead>
      <tr><th>Time</th><th>Category</th><th>Severity</th><th>Title</th><th>Message</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>''' if rows else '<div class="no-issues">✅ No issues detected during this session!</div>'}

</div>
<footer>
  Generated by Android TV Automation System &nbsp;|&nbsp;
  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</footer>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"HTML report saved: {path}")
        return path
