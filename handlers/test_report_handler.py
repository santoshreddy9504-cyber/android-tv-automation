"""
Test Report Handler — generates a detailed QA test report with:
  - Pass / Fail / Slow status per test case
  - Load time measurements with SLA indicators
  - Buffering analysis
  - Issue event log
  - Executive summary
"""

import json
import os
import webbrowser
import logging
from datetime import datetime

from config import config, REPORTS_DIR
from models.test_results import TestSuite, TestStatus, TestCategory
from models.events import SessionStats

logger = logging.getLogger(__name__)


class TestReportHandler:
    def __init__(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)

    def generate(self, suite: TestSuite, stats: SessionStats) -> str:
        if config.report.generate_json_report:
            self._write_json(suite, stats)
        html_path = self._write_html(suite, stats)
        if config.report.auto_open_report and html_path:
            try:
                webbrowser.open(f"file://{html_path}")
            except Exception:
                pass
        return html_path

    # ──────────────────────────────────────────────────────────────────────
    # JSON
    # ──────────────────────────────────────────────────────────────────────

    def _write_json(self, suite: TestSuite, stats: SessionStats) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REPORTS_DIR, f"test_report_{suite.session_id}_{ts}.json")
        data = {
            "test_suite": suite.to_dict(),
            "session_stats": stats.to_dict(),
            "issues": stats.all_events,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"JSON report: {path}")
        return path

    # ──────────────────────────────────────────────────────────────────────
    # HTML
    # ──────────────────────────────────────────────────────────────────────

    def _write_html(self, suite: TestSuite, stats: SessionStats) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REPORTS_DIR, f"test_report_{suite.session_id}_{ts}.html")

        dur_min = stats.duration_seconds / 60

        # ── Status colours ──
        STATUS_COLOR  = {"PASS": "#22cc66", "FAIL": "#ff3333", "SLOW": "#ffaa00", "PENDING": "#888"}
        STATUS_BG     = {"PASS": "#0d2b1a", "FAIL": "#2b0d0d", "SLOW": "#2b1f00", "PENDING": "#1a1a1a"}
        STATUS_ICON   = {"PASS": "✅", "FAIL": "❌", "SLOW": "⚠️", "PENDING": "⏳"}
        CAT_COLOR     = {
            "App Launch":   "#7b9fff",
            "Section Load": "#44ccff",
            "Video Start":  "#aa66ff",
            "Buffering":    "#ff9933",
            "API Call":     "#44ffaa",
            "Navigation":   "#ffdd44",
        }
        ISSUE_CAT_COLOR = {
            "CRASH": "#ff4d4d", "NETWORK": "#ff9933", "PLAYBACK": "#9966ff",
            "UI": "#33aaff", "PERFORMANCE": "#ffcc00", "SYSTEM": "#66cc66",
        }
        ISSUE_SEV_COLOR = {
            "CRITICAL": "#ff2222", "HIGH": "#ff9900",
            "MEDIUM": "#ccaa00", "LOW": "#2266cc", "INFO": "#888",
        }

        def badge(text, color, bg="transparent"):
            return (
                f'<span style="background:{bg or color}22;color:{color};'
                f'padding:2px 10px;border-radius:12px;font-size:0.82em;'
                f'font-weight:bold;border:1px solid {color}44">{text}</span>'
            )

        def ms_bar(duration_ms, threshold_ms):
            if duration_ms is None:
                return "—"
            pct = min((duration_ms / max(threshold_ms, 1)) * 100, 200)
            color = "#22cc66" if pct <= 100 else "#ffaa00" if pct <= 150 else "#ff3333"
            bar_w = min(pct, 100)
            return (
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'<div style="width:100px;background:#1a1d2e;border-radius:4px;overflow:hidden;height:8px">'
                f'<div style="width:{bar_w:.0f}%;background:{color};height:100%"></div></div>'
                f'<span style="color:{color};font-weight:bold">{duration_ms:.0f}ms</span>'
                f'<span style="color:#555;font-size:0.75em">SLA:{threshold_ms:.0f}ms</span>'
                f'</div>'
            )

        # ── Test cases table rows ──
        test_rows = ""
        for tc in suite.test_cases:
            st = tc.status.value
            cat_color = CAT_COLOR.get(tc.category.value, "#888")
            test_rows += (
                f"<tr>"
                f"<td>{tc.started_at.strftime('%H:%M:%S')}</td>"
                f"<td>{badge(tc.category.value, cat_color)}</td>"
                f"<td><strong>{tc.name}</strong>"
                + (f"<br><small style='color:#666'>{tc.failure_reason}</small>" if tc.failure_reason else "")
                + f"</td>"
                f"<td>{ms_bar(tc.duration_ms, tc.threshold_ms)}</td>"
                f"<td style='text-align:center'>{STATUS_ICON[st]} "
                f"<span style='color:{STATUS_COLOR[st]};font-weight:bold'>{st}</span></td>"
                f"</tr>\n"
            )

        if not test_rows:
            test_rows = '<tr><td colspan="5" style="text-align:center;color:#555;padding:30px">No timed events captured yet</td></tr>'

        # ── Buffering rows ──
        buf_rows = ""
        for i, b in enumerate(suite.buffering_events, 1):
            dur = b.duration_ms or 0
            color = "#ff3333" if dur > 5000 else "#ffaa00" if dur > 2000 else "#22cc66"
            if dur > 5000:
                assessment = "<span style='color:#ff3333'>EXCESSIVE</span>"
            elif dur > 2000:
                assessment = "<span style='color:#ffaa00'>SLOW</span>"
            else:
                assessment = "<span style='color:#22cc66'>NORMAL</span>"
            ts_buf = b.started_at.strftime("%H:%M:%S")
            buf_rows += (
                f"<tr><td>#{i}</td>"
                f"<td>{ts_buf}</td>"
                f"<td style='color:{color};font-weight:bold'>{dur:.0f} ms</td>"
                f"<td>{assessment}</td>"
                f"</tr>\n"
            )
        if not buf_rows:
            buf_rows = '<tr><td colspan="4" style="text-align:center;color:#22cc66;padding:20px">✅ No buffering events recorded</td></tr>'

        # ── Issue events table ──
        issue_rows = ""
        for evt in stats.all_events:
            cat  = evt.get("category", "")
            sev  = evt.get("severity", "")
            cc   = ISSUE_CAT_COLOR.get(cat, "#888")
            sc   = ISSUE_SEV_COLOR.get(sev, "#888")
            ts_s = evt.get("timestamp", "")[:19].replace("T", " ")
            issue_rows += (
                f"<tr>"
                f"<td>{ts_s}</td>"
                f"<td>{badge(cat, cc)}</td>"
                f"<td>{badge(sev, sc)}</td>"
                f"<td><strong>{evt.get('title','')}</strong></td>"
                f"<td style='max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>"
                f"{evt.get('message','')[:200]}</td>"
                f"</tr>\n"
            )
        if not issue_rows:
            issue_rows = '<tr><td colspan="5" style="text-align:center;color:#22cc66;padding:20px">✅ No issues detected</td></tr>'

        # ── Category breakdown ──
        by_cat = {}
        for tc in suite.test_cases:
            cat = tc.category.value
            if cat not in by_cat:
                by_cat[cat] = {"pass": 0, "fail": 0, "slow": 0, "times": []}
            if tc.status == TestStatus.PASS:
                by_cat[cat]["pass"] += 1
            elif tc.status == TestStatus.FAIL:
                by_cat[cat]["fail"] += 1
            elif tc.status == TestStatus.SLOW:
                by_cat[cat]["slow"] += 1
            if tc.duration_ms:
                by_cat[cat]["times"].append(tc.duration_ms)

        cat_cards = ""
        for cat, data in by_cat.items():
            avg = sum(data["times"]) / len(data["times"]) if data["times"] else 0
            color = CAT_COLOR.get(cat, "#888")
            total = data["pass"] + data["fail"] + data["slow"]
            cat_cards += f"""
            <div class="cat-card" style="border-left:4px solid {color}">
              <div style="color:{color};font-weight:bold;font-size:0.9em">{cat}</div>
              <div style="margin:10px 0">
                <span style="color:#22cc66">✅ {data['pass']}</span> &nbsp;
                <span style="color:#ff3333">❌ {data['fail']}</span> &nbsp;
                <span style="color:#ffaa00">⚠️ {data['slow']}</span>
              </div>
              <div style="color:#888;font-size:0.8em">Avg: {avg:.0f}ms / {total} tests</div>
            </div>"""

        # ── Overall verdict ──
        pass_rate = suite.pass_rate
        if pass_rate >= 90:
            verdict_color = "#22cc66"
            verdict_text  = "EXCELLENT"
            verdict_icon  = "🟢"
        elif pass_rate >= 70:
            verdict_color = "#ffaa00"
            verdict_text  = "ACCEPTABLE"
            verdict_icon  = "🟡"
        else:
            verdict_color = "#ff3333"
            verdict_text  = "NEEDS ATTENTION"
            verdict_icon  = "🔴"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ROD TV QA Test Report — {suite.session_id}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#0b0d14;color:#e0e0e0;line-height:1.5}}
  a{{color:#7b9fff}}
  header{{background:linear-gradient(135deg,#12152a,#1e2240);padding:28px 40px;border-bottom:2px solid #2a3060}}
  header h1{{font-size:1.7em;color:#7b9fff;margin-bottom:4px}}
  header p{{color:#6677aa;font-size:0.9em}}
  .container{{max-width:1400px;margin:0 auto;padding:28px 40px}}
  h2{{color:#7b9fff;margin:32px 0 14px;font-size:1.1em;text-transform:uppercase;letter-spacing:1px;
      border-bottom:1px solid #1e2240;padding-bottom:8px}}
  .summary-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;margin:20px 0}}
  .metric{{background:#12152a;border-radius:10px;padding:18px 14px;border-left:4px solid #4a6fff}}
  .metric-val{{font-size:2em;font-weight:bold;color:#fff}}
  .metric-lbl{{color:#6677aa;font-size:0.78em;margin-top:4px;text-transform:uppercase}}
  .cat-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin:16px 0}}
  .cat-card{{background:#12152a;border-radius:10px;padding:16px}}
  table{{width:100%;border-collapse:collapse;background:#12152a;border-radius:10px;overflow:hidden;margin-bottom:10px}}
  th{{background:#1a1e38;padding:11px 13px;text-align:left;color:#6677aa;font-size:0.78em;text-transform:uppercase;letter-spacing:.5px}}
  td{{padding:10px 13px;border-top:1px solid #1a1e38;font-size:0.88em;vertical-align:middle}}
  tr:hover td{{background:#161928}}
  .verdict-box{{background:#12152a;border:2px solid {verdict_color};border-radius:12px;
               padding:24px 32px;margin:24px 0;display:flex;align-items:center;gap:20px}}
  .verdict-icon{{font-size:2.5em}}
  .verdict-label{{font-size:1.5em;font-weight:bold;color:{verdict_color}}}
  .verdict-sub{{color:#6677aa;font-size:0.9em;margin-top:4px}}
  footer{{text-align:center;color:#333;padding:24px;font-size:0.78em;border-top:1px solid #1a1e38}}
</style>
</head>
<body>

<header>
  <h1>📺 ROD TV — QA Test Report</h1>
  <p>
    Session: <strong>{suite.session_id}</strong> &nbsp;|&nbsp;
    App: <strong>{config.app.package_name}</strong> &nbsp;|&nbsp;
    Device: <strong>VU 4K TV · Android 12</strong> &nbsp;|&nbsp;
    Started: {stats.start_time.strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp;
    Duration: {dur_min:.1f} min
  </p>
</header>

<div class="container">

  <!-- ── Verdict ── -->
  <div class="verdict-box">
    <div class="verdict-icon">{verdict_icon}</div>
    <div>
      <div class="verdict-label">{verdict_text} — {pass_rate:.1f}% Pass Rate</div>
      <div class="verdict-sub">
        {suite.total} tests executed &nbsp;·&nbsp;
        {suite.passed} passed &nbsp;·&nbsp;
        {suite.slow} slow &nbsp;·&nbsp;
        {suite.failed} failed &nbsp;·&nbsp;
        {suite.buffering_count} buffering events
      </div>
    </div>
  </div>

  <!-- ── Summary metrics ── -->
  <h2>Session Metrics</h2>
  <div class="summary-grid">
    <div class="metric" style="border-color:#22cc66">
      <div class="metric-val">{suite.total}</div><div class="metric-lbl">Tests Run</div>
    </div>
    <div class="metric" style="border-color:#22cc66">
      <div class="metric-val" style="color:#22cc66">{suite.passed}</div><div class="metric-lbl">Passed</div>
    </div>
    <div class="metric" style="border-color:#ffaa00">
      <div class="metric-val" style="color:#ffaa00">{suite.slow}</div><div class="metric-lbl">Slow</div>
    </div>
    <div class="metric" style="border-color:#ff3333">
      <div class="metric-val" style="color:#ff3333">{suite.failed}</div><div class="metric-lbl">Failed</div>
    </div>
    <div class="metric" style="border-color:#aa66ff">
      <div class="metric-val">{suite.avg_load_ms:.0f}</div><div class="metric-lbl">Avg Load (ms)</div>
    </div>
    <div class="metric" style="border-color:#ff9933">
      <div class="metric-val">{suite.buffering_count}</div><div class="metric-lbl">Buffer Events</div>
    </div>
    <div class="metric" style="border-color:#ff9933">
      <div class="metric-val">{suite.total_buffering_ms/1000:.1f}s</div><div class="metric-lbl">Total Buffering</div>
    </div>
    <div class="metric" style="border-color:#ff4d4d">
      <div class="metric-val">{stats.crash_count}</div><div class="metric-lbl">Crashes</div>
    </div>
    <div class="metric" style="border-color:#ffcc00">
      <div class="metric-val">{stats.peak_cpu:.1f}%</div><div class="metric-lbl">Peak CPU</div>
    </div>
    <div class="metric" style="border-color:#44cc88">
      <div class="metric-val">{stats.peak_memory_mb:.0f}</div><div class="metric-lbl">Peak Mem MB</div>
    </div>
  </div>

  <!-- ── Category breakdown ── -->
  <h2>Results by Category</h2>
  <div class="cat-cards">
    {cat_cards if cat_cards else '<p style="color:#555">No categorised results yet.</p>'}
  </div>

  <!-- ── Test cases ── -->
  <h2>Test Case Detail</h2>
  <table>
    <thead>
      <tr><th>Time</th><th>Category</th><th>Test</th><th>Load Time</th><th>Result</th></tr>
    </thead>
    <tbody>{test_rows}</tbody>
  </table>

  <!-- ── Buffering ── -->
  <h2>Buffering Events</h2>
  <table>
    <thead><tr><th>#</th><th>Started</th><th>Duration</th><th>Assessment</th></tr></thead>
    <tbody>{buf_rows}</tbody>
  </table>

  <!-- ── Issues ── -->
  <h2>Detected Issues ({stats.total_issues})</h2>
  <table>
    <thead><tr><th>Time</th><th>Category</th><th>Severity</th><th>Title</th><th>Message</th></tr></thead>
    <tbody>{issue_rows}</tbody>
  </table>

  <!-- ── SLA reference ── -->
  <h2>SLA Thresholds Used</h2>
  <table style="max-width:500px">
    <thead><tr><th>Test Type</th><th>SLA (ms)</th><th>SLA (s)</th></tr></thead>
    <tbody>
      <tr><td>App Cold Start</td><td>8,000</td><td>8.0s</td></tr>
      <tr><td>Section / Screen Load</td><td>4,000</td><td>4.0s</td></tr>
      <tr><td>Video Playback Start</td><td>5,000</td><td>5.0s</td></tr>
      <tr><td>API Response</td><td>3,000</td><td>3.0s</td></tr>
      <tr><td>Buffering (acceptable)</td><td>3,000</td><td>3.0s</td></tr>
    </tbody>
  </table>

</div>
<footer>
  Generated by Android TV Automation System &nbsp;·&nbsp;
  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</footer>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"HTML report: {path}")
        return path
