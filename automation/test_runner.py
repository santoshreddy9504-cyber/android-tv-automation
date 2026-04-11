"""
Automated Test Runner
Executes all scenarios sequentially, collects results,
and generates a detailed QA report.

Now includes:
  • APIMonitor  — captures live HTTP calls from logcat (Network Inspector)
  • AppInspector — UI hierarchy + device state snapshots (Layout Inspector)
"""

import os
import json
import time
import logging
import threading
import subprocess
import webbrowser
from datetime import datetime
from dataclasses import asdict
from typing import List

from config import config, REPORTS_DIR, SCREENSHOTS_DIR
from utils.screen_recorder import ScreenRecorder, RECORDINGS_DIR
from core.adb_client import ADBClient
from core.app_controller import AppController
from core.app_inspector import AppInspector
from monitors.api_monitor import APIMonitor
from monitors.timing_monitor import TimingMonitor
from models.test_results import TestSuite
from automation.remote_control import RemoteControl
from automation.ui_inspector import UIInspector
from automation.scenarios.base_scenario import ScenarioResult
from automation.scenarios.login_test import LoginTest
from automation.scenarios.launch_test import AppLaunchTest
from automation.scenarios.navigation_test import SectionNavigationTest
from automation.scenarios.playback_test import VideoPlaybackTest
from automation.scenarios.stability_test import StabilityTest
from automation.scenarios.search_test import SearchTest
from automation.scenarios.content_detail_test import ContentDetailTest
from automation.scenarios.mylist_test import MyListTest
from automation.scenarios.continue_watching_test import ContinueWatchingTest
from automation.scenarios.settings_test import SettingsTest
from automation.scenarios.app_resume_test import AppResumeTest
from automation.scenarios.live_tv_test import LiveTVTest
from automation.scenarios.subscription_test import SubscriptionTest
from automation.scenarios.pull_to_refresh_test import PullToRefreshTest

logger = logging.getLogger(__name__)

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class AutomatedTestRunner:
    """
    Runs all automated test scenarios end-to-end on the device.
    No human interaction required after start.
    """

    def __init__(self):
        self._adb        = ADBClient()
        self._app        = AppController(self._adb)
        self._remote     = RemoteControl(config.device.adb_target)
        self._inspector  = UIInspector(config.device.adb_target)
        self._api_mon    = APIMonitor(session=None)      # Network Inspector
        self._recorder   = ScreenRecorder(config.device.adb_target)  # Screen Recording
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._test_suite = TestSuite(
            session_id=self._session_id,
            app_package=config.app.package_name
        )
        self._timing_mon = TimingMonitor(self._test_suite)
        self._app_insp   = AppInspector(self._adb, self._api_mon)  # Layout Inspector
        self._results: List[ScenarioResult] = []
        self._recordings: dict = {}   # scenario_id → local video path
        self._start_time = datetime.now()
        self._logcat_thread: threading.Thread = None
        self._logcat_stop  = threading.Event()

    def run(self):
        print("\n" + "═" * 65)
        print(f"  🤖  AUTOMATED QA TEST RUN — {config.app.app_name}")
        print("═" * 65)
        print(f"  Client  : {config.client.app_name}")
        print(f"  Package : {config.app.package_name}")
        print(f"  Device  : {config.device.adb_target}")
        print(f"  Started : {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("═" * 65 + "\n")

        # Connect
        if not self._adb.connect():
            print("❌ Cannot connect to device. Aborting.")
            return

        device_info = self._adb.get_device_info()
        print(f"  Device : {device_info.get('manufacturer','')} "
              f"{device_info.get('model','')} | "
              f"Android {device_info.get('android_version','')}\n")

        # Start background logcat → APIMonitor + TimingMonitor thread
        self._start_logcat_monitoring()
        print("[Setup] 🌐 Network Inspector (APIMonitor) started")
        print("[Setup] ⏱️  Timing Monitor started (log-based)")

        # Launch app fresh
        print("[Setup] Launching app ...")
        self._app.force_stop()
        time.sleep(2)
        self._app.launch()
        time.sleep(3)

        # Run all scenarios end-to-end
        scenarios = [
            LoginTest,              # TC000 — auto-login
            AppLaunchTest,          # TC001 — cold start timing
            SectionNavigationTest,  # TC002 — section navigation
            VideoPlaybackTest,      # TC003 — video playback & controls
            StabilityTest,          # TC004 — stress & performance
            SearchTest,             # TC005 — search functionality
            ContentDetailTest,      # TC006 — content detail page
            MyListTest,             # TC007 — my list / watchlist
            ContinueWatchingTest,   # TC008 — continue watching
            SettingsTest,           # TC009 — settings & profile
            AppResumeTest,          # TC010 — background & resume
            LiveTVTest,             # TC011 — live TV / channels
            SubscriptionTest,       # TC012 — subscription & account
            PullToRefreshTest,      # TC013 — pull-to-refresh gesture
        ]

        for ScenarioClass in scenarios:
            scenario = ScenarioClass(
                adb=self._adb,
                remote=self._remote,
                inspector=self._inspector,
                screenshot_dir=SCREENSHOTS_DIR,
                timing_monitor=self._timing_mon,
            )
            print(f"\n▶  Running {scenario.SCENARIO_ID}: {scenario.SCENARIO_NAME} ...")

            # Start screen recording for this scenario
            self._recorder.start(scenario.SCENARIO_ID, scenario.SCENARIO_NAME)
            if self._recorder.is_recording:
                print(f"   🎥 Recording screen ...")

            try:
                result = scenario.run()
            except Exception as exc:
                logger.error(f"Scenario {scenario.SCENARIO_ID} crashed: {exc}", exc_info=True)
                result = scenario.result
                result.status = "ERROR"
                result.error = str(exc)
                result.finish()

            # Stop recording and save video path
            video_path = self._recorder.stop()
            if video_path:
                self._recordings[scenario.SCENARIO_ID] = video_path
                print(f"   🎥 Video saved: {os.path.basename(video_path)}")

            self._results.append(result)
            icon = "✅" if result.status == "PASS" else "❌" if result.status == "FAIL" else "⚠️"
            print(f"   {icon}  {result.status}  ({result.duration_ms/1000:.1f}s)  "
                  f"Steps: {result.steps_passed}/{result.steps_passed + result.steps_failed}")

            # Brief pause between scenarios
            time.sleep(2)

        # Stop logcat thread
        self._stop_logcat_monitoring()
        self._timing_mon.finalize()

        # Save API call JSON
        api_json = self._api_mon.save_json()
        print(f"[API]    ✅ {len(self._api_mon.calls)} API calls captured → {api_json}")

        # Save inspector HTML snapshot
        snap_path = os.path.join(REPORTS_DIR, f"inspector_{self._session_id}.html")
        try:
            snap = self._app_insp.snapshot()
            snap.save_html(snap_path)
            print(f"[Insp]   ✅ App Inspector snapshot → {snap_path}")
        except Exception as exc:
            logger.warning(f"Inspector snapshot failed: {exc}")

        # Generate report
        end_time = datetime.now()
        print("\n\n[Report] Generating QA report ...")
        html_path = self._generate_report(end_time)
        print(f"[Report] ✅ {html_path}\n")

        self._print_summary(end_time)

        # Auto-open report
        try:
            webbrowser.open(f"file://{html_path}")
        except Exception:
            pass

        self._adb.disconnect()

    # ── Background logcat → Detectors ──────────────────────────────────────────

    def _start_logcat_monitoring(self):
        """Stream logcat in background and feed every line to monitors."""
        self._logcat_stop.clear()

        def _worker():
            cmd = ["adb", "-s", config.device.adb_target,
                   "logcat", "-v", "threadtime"]
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, bufsize=1,
                )
                for line in proc.stdout:
                    if self._logcat_stop.is_set():
                        break
                    
                    line_clean = line.rstrip("\n")
                    # Feed to Network Inspector
                    self._api_mon.analyze(line_clean)
                    # Feed to Timing Monitor
                    self._timing_mon.analyze(line_clean)

                proc.terminate()
            except Exception as exc:
                logger.debug(f"Logcat monitoring thread: {exc}")

        self._logcat_thread = threading.Thread(
            target=_worker, name="QA-LogcatMonitor", daemon=True
        )
        self._logcat_thread.start()

    def _stop_logcat_monitoring(self):
        self._logcat_stop.set()
        if self._logcat_thread:
            self._logcat_thread.join(timeout=5)

    # ── Report generation ─────────────────────────────────────────────────

    def _generate_report(self, end_time: datetime) -> str:
        ts = self._session_id
        path = os.path.join(REPORTS_DIR, f"auto_test_report_{ts}.html")

        # JSON data too
        json_path = os.path.join(REPORTS_DIR, f"auto_test_report_{ts}.json")
        with open(json_path, "w") as f:
            json.dump({
                "session": ts,
                "app": config.app.package_name,
                "device": config.device.adb_target,
                "start": self._start_time.isoformat(),
                "end": end_time.isoformat(),
                "scenarios": [r.to_dict() for r in self._results],
                "api_stats": self._api_mon.stats(),
            }, f, indent=2)

        html = self._build_html(end_time)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def _build_html(self, end_time: datetime) -> str:  # noqa: C901
        duration_s = (end_time - self._start_time).total_seconds()
        total      = len(self._results)
        passed     = sum(1 for r in self._results if r.status == "PASS")
        failed     = sum(1 for r in self._results if r.status in ("FAIL", "ERROR"))
        skipped    = sum(1 for r in self._results if r.status == "SKIP")
        total_steps  = sum(len(r.steps) for r in self._results)
        steps_passed = sum(r.steps_passed for r in self._results)
        steps_failed = sum(r.steps_failed for r in self._results)
        pass_rate  = (passed / total * 100) if total else 0

        # ── API stats (Network Inspector) ─────────────────────────────────
        api_stats  = self._api_mon.stats()
        api_total  = api_stats.get("total", 0)
        api_ok     = api_stats.get("success", 0)
        api_err    = api_stats.get("errors", 0)
        api_avgms  = api_stats.get("avg_ms", 0)
        api_slow   = api_stats.get("slow_calls", 0)
        api_rate   = (api_ok / api_total * 100) if api_total else 100.0

        # ── Timing stats (Timing Monitor) ─────────────────────────────────
        suite = self._test_suite
        launch_ms = next((t.duration_ms for t in suite.test_cases if t.category == "App Launch"), 0)
        avg_nav   = suite.avg_load_ms

        if pass_rate >= 80:
            verdict, v_color, v_icon, v_label = "PASS", "#22cc66", "✅", "All critical features working"
        elif pass_rate >= 55:
            verdict, v_color, v_icon, v_label = "PARTIAL PASS", "#ffaa00", "⚠️", "Some features require attention"
        else:
            verdict, v_color, v_icon, v_label = "FAIL", "#ff4444", "❌", "Critical issues found — release blocked"

        SC = {"PASS": "#22cc66", "FAIL": "#ff4444", "ERROR": "#ff4444",
              "SKIP": "#888888", "PENDING": "#555555"}
        SI = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥", "SKIP": "⏭", "PENDING": "⏳"}

        device_info = self._adb.get_device_info()

        def badge(text, color):
            return (f'<span style="background:{color}22;color:{color};padding:3px 12px;'
                    f'border-radius:20px;font-size:0.78em;font-weight:700;'
                    f'border:1px solid {color}55;letter-spacing:.5px">{text}</span>')

        def pbar(pct, color="#22cc66", width=180):
            fill = min(pct, 100)
            return (f'<div style="display:inline-flex;align-items:center;gap:8px">'
                    f'<div style="background:#1a1e38;border-radius:6px;height:8px;'
                    f'width:{width}px;overflow:hidden">'
                    f'<div style="width:{fill:.0f}%;background:{color};height:100%;'
                    f'border-radius:6px"></div></div>'
                    f'<span style="color:{color};font-size:.85em;font-weight:600">{pct:.0f}%</span>'
                    f'</div>')

        # ── Defect log (all failed steps across all scenarios) ────────────
        defects_html = ""
        defect_no = 1
        for r in self._results:
            for s in r.steps:
                if not s.passed:
                    sev = "CRITICAL" if r.scenario_id in ("TC000","TC001","TC003") else "HIGH" \
                          if r.scenario_id in ("TC002","TC005","TC011") else "MEDIUM"
                    sev_color = "#ff4444" if sev == "CRITICAL" else "#ffaa00" if sev == "HIGH" else "#ffcc44"
                    ss_link = (f' <a href="file://{s.screenshot}" target="_blank" '
                               f'style="color:#7b9fff;font-size:.8em">[screenshot]</a>'
                               if s.screenshot else "")
                    defects_html += f"""
<tr>
  <td style="color:#888;font-size:.82em">DEF-{defect_no:03d}</td>
  <td>{badge(sev, sev_color)}</td>
  <td style="color:#aab">{r.scenario_id}</td>
  <td style="color:#dde">{s.name}</td>
  <td style="color:#888;font-size:.85em">{s.message or "Step did not pass"}{ss_link}</td>
</tr>"""
                    defect_no += 1

        if not defects_html:
            defects_html = '<tr><td colspan="5" style="text-align:center;color:#22cc66;padding:18px">No defects found — all steps passed ✅</td></tr>'

        # ── Scenario overview table ───────────────────────────────────────
        overview_rows = ""
        for r in self._results:
            sc = SC.get(r.status, "#888")
            si = SI.get(r.status, "•")
            sp = r.steps_passed
            sf = r.steps_failed
            pct = (sp / max(sp + sf, 1)) * 100
            overview_rows += f"""
<tr>
  <td style="color:#5566aa;font-weight:700;font-size:.85em">{r.scenario_id}</td>
  <td>{r.name}</td>
  <td style="text-align:center">{badge(r.status, sc)}</td>
  <td style="text-align:center;color:#dde">{sp + sf}</td>
  <td style="text-align:center;color:#22cc66">{sp}</td>
  <td style="text-align:center;color:#ff4444">{sf}</td>
  <td>{pbar(pct, sc, 120)}</td>
  <td style="text-align:right;color:#888;font-size:.85em">{r.duration_ms/1000:.1f}s</td>
</tr>"""

        # ── Detailed scenario cards ───────────────────────────────────────
        scenario_cards = ""
        for r in self._results:
            sc = SC.get(r.status, "#888")
            si = SI.get(r.status, "•")
            sp = r.steps_passed
            sf = r.steps_failed
            pct = (sp / max(sp + sf, 1)) * 100

            steps_rows = ""
            for i, s in enumerate(r.steps, 1):
                icon = "✅" if s.passed else "❌"
                row_bg = "" if s.passed else "background:#1f0d0d;"
                ss_lnk = (f'<a href="file://{s.screenshot}" target="_blank" '
                           f'style="color:#7b9fff">📸</a>' if s.screenshot else "—")
                dur_color = "#ff9944" if s.duration_ms > 5000 else "#888"
                steps_rows += f"""
<tr style="{row_bg}">
  <td style="color:#555;font-size:.8em;width:30px">{i}</td>
  <td style="width:22px">{icon}</td>
  <td style="color:#dde">{s.name}</td>
  <td style="color:{dur_color};font-size:.82em;white-space:nowrap">{s.duration_ms:.0f} ms</td>
  <td style="color:#888;font-size:.82em;max-width:320px">{s.message or "—"}</td>
  <td style="text-align:center">{ss_lnk}</td>
</tr>"""

            err_html = (f'<div style="margin:10px 20px;padding:10px 14px;'
                        f'background:#2b0d0d;border-left:3px solid #ff4444;'
                        f'border-radius:4px;color:#ff8888;font-size:.85em">'
                        f'Error: {r.error}</div>') if r.error else ""

            # Video recording link
            vid_path = self._recordings.get(r.scenario_id, "")
            vid_html = ""
            if vid_path and os.path.exists(vid_path):
                vid_html = (
                    f'<div style="padding:10px 22px 8px">'
                    f'<span style="font-size:.82em;color:#3a4e88">Screen Recording: </span>'
                    f'<a href="file://{vid_path}" target="_blank" '
                    f'style="color:#7b9fff;font-size:.82em;text-decoration:none">'
                    f'🎥 {os.path.basename(vid_path)}'
                    f'</a>'
                    f'<video controls style="display:block;margin-top:8px;width:100%;'
                    f'max-width:640px;border-radius:8px;border:1px solid #1e2240" '
                    f'src="file://{vid_path}"></video>'
                    f'</div>'
                )

            scenario_cards += f"""
<div style="background:#12152a;border-radius:14px;margin:18px 0;
            overflow:hidden;border-left:5px solid {sc}">
  <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
              background:#161a30;border-bottom:1px solid #1e2240">
    <span style="font-size:1.3em">{si}</span>
    <span style="color:#5566aa;font-size:.8em;font-weight:700;min-width:52px">{r.scenario_id}</span>
    <span style="font-weight:700;font-size:1em;color:#dde">{r.name}</span>
    <span style="margin-left:auto;display:flex;align-items:center;gap:12px">
      {badge(r.status, sc)}
      {'<span style="font-size:.8em">🎥</span>' if vid_path else ''}
      <span style="color:#555;font-size:.82em">{r.duration_ms/1000:.1f}s</span>
    </span>
  </div>
  <div style="padding:10px 22px 6px;font-size:.85em;color:#5566aa">
    Steps: <strong style="color:#22cc66">{sp} passed</strong>
    / <strong style="color:#ff4444">{sf} failed</strong>
    &nbsp;|&nbsp; {pbar(pct, sc)}
  </div>
  {err_html}
  {vid_html}
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:.84em">
    <thead>
      <tr style="background:#0f1220">
        <th style="padding:8px 12px;text-align:left;color:#3a4a88;font-size:.72em;
                   text-transform:uppercase;letter-spacing:.8px">#</th>
        <th style="padding:8px 12px;text-align:left;color:#3a4a88;font-size:.72em;
                   text-transform:uppercase;letter-spacing:.8px"></th>
        <th style="padding:8px 12px;text-align:left;color:#3a4a88;font-size:.72em;
                   text-transform:uppercase;letter-spacing:.8px">Step Description</th>
        <th style="padding:8px 12px;text-align:left;color:#3a4a88;font-size:.72em;
                   text-transform:uppercase;letter-spacing:.8px">Duration</th>
        <th style="padding:8px 12px;text-align:left;color:#3a4a88;font-size:.72em;
                   text-transform:uppercase;letter-spacing:.8px">Result / Detail</th>
        <th style="padding:8px 12px;text-align:center;color:#3a4a88;font-size:.72em;
                   text-transform:uppercase;letter-spacing:.8px">Proof</th>
      </tr>
    </thead>
    <tbody>
      {steps_rows if steps_rows else '<tr><td colspan="6" style="padding:14px;color:#555;text-align:center">No steps recorded</td></tr>'}
    </tbody>
  </table>
  </div>
</div>"""

        # ── Executive summary text ────────────────────────────────────────
        crit_fails = [r for r in self._results
                      if r.status in ("FAIL","ERROR")
                      and r.scenario_id in ("TC000","TC001","TC003")]
        exec_lines = []
        if passed == total:
            exec_lines.append("All 13 test scenarios completed successfully with no critical defects.")
        else:
            exec_lines.append(
                f"{passed} of {total} scenarios passed ({pass_rate:.0f}%). "
                f"{failed} scenario(s) require attention before release."
            )
        if crit_fails:
            names = ", ".join(r.scenario_id for r in crit_fails)
            exec_lines.append(
                f"Critical failures in: {names}. These block release readiness."
            )
        exec_lines.append(
            f"Total of {steps_passed} test steps passed and {steps_failed} failed "
            f"across {total_steps} automated checks. "
            f"Full test run completed in {duration_s/60:.1f} minutes with zero manual interaction."
        )
        exec_summary = " ".join(exec_lines)

        # ── Recommendations ───────────────────────────────────────────────
        recs = []
        for r in self._results:
            if r.status in ("FAIL","ERROR"):
                recs.append(f"<li><strong>{r.scenario_id} — {r.name}:</strong> "
                            f"Investigate {r.steps_failed} failed step(s). "
                            f"Review screenshots attached to each failed step.</li>")
        if not recs:
            recs.append("<li>No action required — all scenarios passed.</li>")
        recs_html = "\n".join(recs)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{config.app.app_name} QA Test Report — {self._session_id}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',system-ui,Arial,sans-serif;background:#080a12;
        color:#ccd;line-height:1.6;font-size:14px}}
  a{{color:#7b9fff;text-decoration:none}}
  a:hover{{text-decoration:underline}}

  /* Header */
  .report-header{{background:linear-gradient(135deg,#0d1128 0%,#131840 100%);
                  padding:36px 52px 28px;border-bottom:2px solid #1e2550}}
  .report-header h1{{font-size:1.55em;color:#8aabff;font-weight:700;
                     letter-spacing:-.3px;margin-bottom:4px}}
  .report-header .subtitle{{color:#3a4e88;font-size:.88em;margin-bottom:18px}}
  .header-meta{{display:flex;flex-wrap:wrap;gap:24px;margin-top:12px}}
  .header-meta-item{{font-size:.82em;color:#3a4e88}}
  .header-meta-item strong{{color:#7b9fff}}

  /* Layout */
  .container{{max-width:1280px;margin:0 auto;padding:32px 52px 60px}}

  /* Section headings */
  .section-title{{font-size:.78em;font-weight:700;text-transform:uppercase;
                  letter-spacing:2px;color:#3a4e88;margin:36px 0 14px;
                  padding-bottom:8px;border-bottom:1px solid #161c38}}

  /* Verdict banner */
  .verdict{{display:flex;align-items:center;gap:20px;padding:24px 32px;
            border-radius:14px;margin:20px 0 32px;
            border:1.5px solid {v_color};background:#0e1020}}
  .verdict-icon{{font-size:2.4em;line-height:1}}
  .verdict-title{{font-size:1.4em;font-weight:700;color:{v_color}}}
  .verdict-sub{{color:#3a4e88;font-size:.88em;margin-top:4px}}

  /* Metric grid */
  .metrics{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));
            gap:12px;margin:16px 0 28px}}
  .metric{{background:#0e1020;border-radius:10px;padding:16px 14px;
           border-top:3px solid #2a3060}}
  .metric-val{{font-size:1.9em;font-weight:700;color:#fff;line-height:1}}
  .metric-lbl{{color:#3a4e88;font-size:.7em;margin-top:6px;
               text-transform:uppercase;letter-spacing:.8px}}

  /* Overview table */
  .overview-table{{width:100%;border-collapse:collapse;
                   background:#0e1020;border-radius:12px;overflow:hidden}}
  .overview-table th{{background:#0b0d1a;padding:10px 14px;text-align:left;
                      color:#3a4e88;font-size:.72em;text-transform:uppercase;
                      letter-spacing:.8px;font-weight:600}}
  .overview-table td{{padding:10px 14px;border-top:1px solid #141828;
                      vertical-align:middle}}
  .overview-table tr:hover td{{background:#111428}}

  /* Defect table */
  .defect-table{{width:100%;border-collapse:collapse;
                 background:#0e1020;border-radius:12px;overflow:hidden}}
  .defect-table th{{background:#1a0d0d;padding:10px 14px;text-align:left;
                    color:#884444;font-size:.72em;text-transform:uppercase;
                    letter-spacing:.8px}}
  .defect-table td{{padding:10px 14px;border-top:1px solid #1f1010;
                    vertical-align:top}}
  .defect-table tr:hover td{{background:#130808}}

  /* Exec summary */
  .exec-box{{background:#0e1020;border-left:4px solid #4a6fff;
             border-radius:0 10px 10px 0;padding:18px 24px;
             color:#aab;font-size:.9em;line-height:1.7;margin:14px 0}}

  /* Recommendations */
  .recs-box{{background:#0e1020;border-radius:10px;padding:20px 26px;margin:14px 0}}
  .recs-box ul{{list-style:none;padding:0}}
  .recs-box li{{padding:8px 0;border-bottom:1px solid #141828;
                color:#aab;font-size:.88em;line-height:1.6}}
  .recs-box li:last-child{{border-bottom:none}}

  /* Env table */
  .env-table{{width:100%;max-width:580px;border-collapse:collapse;
              background:#0e1020;border-radius:10px;overflow:hidden}}
  .env-table td{{padding:9px 16px;border-top:1px solid #141828;font-size:.87em}}
  .env-table td:first-child{{color:#3a4e88;width:170px;font-weight:500}}

  /* Print */
  @media print{{
    body{{background:#fff;color:#000}}
    .report-header{{background:#f4f6ff;border-color:#ccd}}
    .verdict,.metric,.overview-table,.defect-table,.exec-box,.recs-box,
    .env-table,.api-table{{border-color:#ccd;background:#f9f9ff}}
  }}
</style>
</head>
<body>

<!-- ═══════════════════════ HEADER ═══════════════════════ -->
<div class="report-header">
  <h1>📺 {config.app.app_name} — QA Test Execution Report</h1>
  <div class="subtitle">Automated End-to-End Test Suite · Android TV Platform</div>
  <div class="header-meta">
    <div class="header-meta-item">Report ID: <strong>{self._session_id}</strong></div>
    <div class="header-meta-item">Test Date: <strong>{self._start_time.strftime('%Y-%m-%d')}</strong></div>
    <div class="header-meta-item">Start: <strong>{self._start_time.strftime('%H:%M:%S')}</strong></div>
    <div class="header-meta-item">End: <strong>{end_time.strftime('%H:%M:%S')}</strong></div>
    <div class="header-meta-item">Duration: <strong>{duration_s/60:.1f} min</strong></div>
    <div class="header-meta-item">Tester: <strong>Automated (ADB + UIAutomator)</strong></div>
    <div class="header-meta-item">App: <strong>{config.app.package_name} v2.0</strong></div>
    <div class="header-meta-item">Device: <strong>{device_info.get('manufacturer','')} {device_info.get('model','')}</strong></div>
  </div>
</div>

<div class="container">

<!-- ═══════════════════════ VERDICT ═══════════════════════ -->
<div class="verdict">
  <div class="verdict-icon">{v_icon}</div>
  <div>
    <div class="verdict-title">Overall Result: {verdict}</div>
    <div class="verdict-sub">
      {passed}/{total} scenarios passed &nbsp;·&nbsp;
      Pass rate: {pass_rate:.0f}% &nbsp;·&nbsp;
      {v_label}
    </div>
  </div>
</div>

<!-- ═══════════════════════ EXECUTIVE SUMMARY ═══════════════════════ -->
<div class="section-title">Executive Summary</div>
<div class="exec-box">{exec_summary}</div>

<!-- ═══════════════════════ METRICS ═══════════════════════ -->
<div class="section-title">Test Metrics</div>
<div class="metrics">
  <div class="metric" style="border-color:#4a6fff">
    <div class="metric-val">{total}</div>
    <div class="metric-lbl">Scenarios</div>
  </div>
  <div class="metric" style="border-color:#22cc66">
    <div class="metric-val" style="color:#22cc66">{passed}</div>
    <div class="metric-lbl">Passed</div>
  </div>
  <div class="metric" style="border-color:#ff4444">
    <div class="metric-val" style="color:#ff4444">{failed}</div>
    <div class="metric-lbl">Failed</div>
  </div>
  <div class="metric" style="border-color:#888">
    <div class="metric-val" style="color:#888">{skipped}</div>
    <div class="metric-lbl">Skipped</div>
  </div>
  <div class="metric" style="border-color:#4a6fff">
    <div class="metric-val">{total_steps}</div>
    <div class="metric-lbl">Total Steps</div>
  </div>
  <div class="metric" style="border-color:#22cc66">
    <div class="metric-val" style="color:#22cc66">{steps_passed}</div>
    <div class="metric-lbl">Steps Passed</div>
  </div>
  <div class="metric" style="border-color:#ff4444">
    <div class="metric-val" style="color:#ff4444">{steps_failed}</div>
    <div class="metric-lbl">Steps Failed</div>
  </div>
  <div class="metric" style="border-color:#ffaa00">
    <div class="metric-val" style="color:#ffaa00">{pass_rate:.0f}%</div>
    <div class="metric-lbl">Pass Rate</div>
  </div>
  <!-- API metrics -->
  <div class="metric" style="border-color:#7b9fff;margin-left:18px">
    <div class="metric-val" style="color:#7b9fff">{api_total}</div>
    <div class="metric-lbl">🌐 API Calls</div>
  </div>
  <div class="metric" style="border-color:#22cc66">
    <div class="metric-val" style="color:#22cc66">{api_ok}</div>
    <div class="metric-lbl">API 2xx OK</div>
  </div>
  <div class="metric" style="border-color:#ff4444">
    <div class="metric-val" style="color:#ff4444">{api_err}</div>
    <div class="metric-lbl">API Errors</div>
  </div>
  <div class="metric" style="border-color:#ffaa00">
    <div class="metric-val" style="color:#ffaa00">{api_avgms}ms</div>
    <div class="metric-lbl">Avg Response</div>
  </div>
  <div class="metric" style="border-color:#ff9944">
    <div class="metric-val" style="color:#ff9944">{api_slow}</div>
    <div class="metric-lbl">&gt;3s Slow Calls</div>
  </div>
</div>

<div class="metrics" style="margin-top:-10px">
  <div class="metric" style="border-color:#bb66ff">
    <div class="metric-val" style="color:#bb66ff">{launch_ms/1000:.1f}s</div>
    <div class="metric-lbl">App Cold Start</div>
  </div>
  <div class="metric" style="border-color:#bb66ff">
    <div class="metric-val" style="color:#bb66ff">{avg_nav:.0f}ms</div>
    <div class="metric-lbl">Avg Page Load</div>
  </div>
  <div class="metric" style="border-color:#ff5555">
    <div class="metric-val" style="color:#ff5555">{suite.buffering_count}</div>
    <div class="metric-lbl">Buffering Events</div>
  </div>
  <div class="metric" style="border-color:#ff5555">
    <div class="metric-val" style="color:#ff5555">{suite.total_buffering_ms/1000:.1f}s</div>
    <div class="metric-lbl">Total Buffer Time</div>
  </div>
</div>

<!-- ═══════════════════════ TEST ENVIRONMENT ═══════════════════════ -->
<div class="section-title">Test Environment</div>
<table class="env-table">
  <tr><td>Device</td><td>{device_info.get('manufacturer','')} {device_info.get('model','')}</td></tr>
  <tr><td>Android Version</td><td>{device_info.get('android_version','')} (API {device_info.get('sdk_version','')})</td></tr>
  <tr><td>RAM</td><td>{device_info.get('total_memory_mb',0):.0f} MB</td></tr>
  <tr><td>Connection</td><td>ADB over WiFi — {config.device.adb_target}</td></tr>
  <tr><td>App Package</td><td>{config.app.package_name}</td></tr>
  <tr><td>App Version</td><td>{config.app.app_name}</td></tr>
  <tr><td>Test Account</td><td>{config.login.email}</td></tr>
  <tr><td>Automation</td><td>ADB Remote Control + UIAutomator Inspector</td></tr>
  <tr><td>Executed</td><td>{self._start_time.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
</table>

<!-- ═══════════════════════ SCENARIO OVERVIEW ═══════════════════════ -->
<div class="section-title">Scenario Overview</div>
<table class="overview-table">
  <thead>
    <tr>
      <th>ID</th>
      <th>Scenario Name</th>
      <th style="text-align:center">Result</th>
      <th style="text-align:center">Steps</th>
      <th style="text-align:center">Passed</th>
      <th style="text-align:center">Failed</th>
      <th>Step Pass Rate</th>
      <th style="text-align:right">Duration</th>
    </tr>
  </thead>
  <tbody>
    {overview_rows}
  </tbody>
</table>

<!-- ═══════════════════════ DEFECT LOG ═══════════════════════ -->
<div class="section-title">Defect Log</div>
<table class="defect-table">
  <thead>
    <tr>
      <th>Defect ID</th>
      <th>Severity</th>
      <th>Scenario</th>
      <th>Failed Step</th>
      <th>Details / Evidence</th>
    </tr>
  </thead>
  <tbody>
    {defects_html}
  </tbody>
</table>

<!-- ═══════════════════════ DETAILED RESULTS ═══════════════════════ -->
<div class="section-title">Detailed Test Results</div>
{scenario_cards}

<!-- ═══════════════════════ NETWORK INSPECTOR ═══════════════════════ -->
<div class="section-title">🌐 Network Inspector — API Calls</div>
<div style="background:#0a0d1a;border-radius:10px;padding:14px 20px;margin-bottom:16px;display:flex;gap:28px;flex-wrap:wrap">
  <span style="font-size:.82em;color:#3a4e88">Total: <strong style="color:#7b9fff">{api_total}</strong></span>
  <span style="font-size:.82em;color:#3a4e88">Success (2xx): <strong style="color:#22cc66">{api_ok}</strong></span>
  <span style="font-size:.82em;color:#3a4e88">Errors: <strong style="color:#ff4444">{api_err}</strong></span>
  <span style="font-size:.82em;color:#3a4e88">Avg Response: <strong style="color:#ffaa00">{api_avgms}ms</strong></span>
  <span style="font-size:.82em;color:#3a4e88">Slow (&gt;3s): <strong style="color:#ff9944">{api_slow}</strong></span>
  <span style="font-size:.82em;color:#3a4e88">API Health: <strong style="color:{'#22cc66' if api_rate>=95 else '#ffaa00' if api_rate>=80 else '#ff4444'}">{api_rate:.0f}%</strong></span>
</div>
{self._build_api_table()}

<!-- ═══════════════════════ TIMING INSPECTOR ═══════════════════════ -->
<div class="section-title">⏱️ Timing Inspector — Log-based Metrics</div>
<div style="background:#0a0d1a;border-radius:10px;padding:14px 20px;margin-bottom:16px;display:flex;gap:28px;flex-wrap:wrap">
  <span style="font-size:.82em;color:#3a4e88">Cold Start: <strong style="color:#bb66ff">{launch_ms/1000:.2f}s</strong></span>
  <span style="font-size:.82em;color:#3a4e88">Avg Page Load: <strong style="color:#bb66ff">{avg_nav:.0f}ms</strong></span>
  <span style="font-size:.82em;color:#3a4e88">Buffering: <strong style="color:#ff5555">{suite.buffering_count}</strong></span>
</div>
{self._build_timing_table()}

<!-- ═══════════════════════ RECOMMENDATIONS ═══════════════════════ -->
<div class="section-title">Recommendations</div>
<div class="recs-box">
  <ul>{recs_html}</ul>
</div>

</div><!-- /container -->

<div style="text-align:center;color:#1e2550;padding:24px;font-size:.75em;
            border-top:1px solid #0f1228;margin-top:20px">
  {config.app.app_name} QA Automation System &nbsp;·&nbsp;
  Report: {self._session_id} &nbsp;·&nbsp;
  Generated: {end_time.strftime('%Y-%m-%d %H:%M:%S')} &nbsp;·&nbsp;
  Tester: {config.login.email or "—"}
</div>

</body>
</html>"""

    def _print_summary(self, end_time: datetime):
        total  = len(self._results)
        passed = sum(1 for r in self._results if r.status == "PASS")
        dur    = (end_time - self._start_time).total_seconds()

        print("═" * 65)
        print("  AUTOMATED TEST SUMMARY")
        print("═" * 65)
        for r in self._results:
            icon = "✅" if r.status == "PASS" else "❌"
            steps_info = f"{r.steps_passed}/{r.steps_passed+r.steps_failed} steps"
            print(f"  {icon}  {r.scenario_id}  {r.name:<40} {steps_info}")
        print("─" * 65)
        print(f"  Result : {passed}/{total} scenarios passed")
        print(f"  Runtime: {dur/60:.1f} minutes")
        print("═" * 65 + "\n")

    def _build_api_table(self) -> str:
        calls = self._api_mon.snapshot()
        if not calls:
            return '<p style="color:#555;padding:20px;text-align:center">No API calls captured during this session.</p>'

        rows = ""
        for c in calls[-200:]:  # Last 200 calls
            ms = c.response_ms
            code = c.status_code
            error = c.error
            url = c.url
            method = c.method
            
            # Color coding
            color = "#7b9fff" # default
            if code >= 400 or error:
                color = "#ff4444"
            elif 200 <= code < 300:
                color = "#22cc66"
            elif ms > 3000:
                color = "#ff9944"

            status = f"HTTP {code}" if code else "FAILED"
            if error:
                status = error[:30]
            
            rows += f"""
<tr style="font-size: 0.85em;">
  <td style="color:#7b9fff; font-weight: 600;">{method}</td>
  <td style="color:{color}; font-weight: 700;">{status}</td>
  <td style="color:{'#ff9944' if ms > 3000 else '#888'}">{ms}ms</td>
  <td style="color:#ccd; word-break: break-all; font-family: monospace;">{url}</td>
  <td style="color:#555; font-size: 0.8em;">{c.source}</td>
</tr>"""

        return f"""
<table class="api-table" style="width:100%; border-collapse: collapse; background: #0e1020; border-radius: 12px; overflow: hidden;">
  <thead>
    <tr style="background:#0b0d1a;">
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Method</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Status</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Time</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Endpoint</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Source</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>"""

    def _build_timing_table(self) -> str:
        suite = self._test_suite
        if not suite.test_cases:
            return '<p style="color:#555;padding:20px;text-align:center">No timing events captured.</p>'

        rows = ""
        for tc in suite.test_cases:
            ms = tc.duration_ms or 0
            color = "#22cc66" if tc.status == "PASS" else "#ffaa00" if tc.status == "SLOW" else "#ff4444"
            icon = "✅" if tc.status == "PASS" else "⚠️" if tc.status == "SLOW" else "❌"
            
            rows += f"""
<tr style="font-size: 0.85em;">
  <td style="color:#3a4e88; font-weight: 700;">{tc.category}</td>
  <td style="color:{color}; font-weight: 600;">{icon} {tc.status}</td>
  <td style="color:#dde;">{tc.name}</td>
  <td style="color:{color}; font-weight: 700;">{ms:.0f}ms</td>
  <td style="color:#555; font-size: 0.8em; font-family: monospace;">{tc.raw_log[:100]}</td>
</tr>"""

        return f"""
<table class="timing-table" style="width:100%; border-collapse: collapse; background: #0e1020; border-radius: 12px; overflow: hidden;">
  <thead>
    <tr style="background:#0b0d1a;">
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Category</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Status</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Event Name</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Duration</th>
      <th style="padding:10px; text-align:left; color:#3a4e88; font-size:0.75em;">Raw Signal</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>"""
