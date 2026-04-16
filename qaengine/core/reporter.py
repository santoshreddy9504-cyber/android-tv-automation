"""
Universal HTML Report Generator v2.1
Includes: QA Score gauge, CPU chart, battery info, memory leak flag,
          crash recovery times, event timeline, build comparison,
          steps to reproduce, network errors, focus issues, screen journey,
          CSV export, app version.
"""
import os, json, csv
from datetime import datetime
from typing import List, Optional


def generate_report(
    session_dir: str,
    app_name: str,
    package: str,
    device_info: dict,
    summary: dict,
    analyses_html: List[str],
    manual_alerts_html: List[str],
    recordings: List[str],
    app_version: Optional[dict] = None,
    compare_data: Optional[dict] = None,
    out_path: Optional[str] = None,
) -> str:

    now      = datetime.now()
    date_str = now.strftime("%B %d, %Y")
    out_path = out_path or os.path.join(session_dir, f"QAReport_{now.strftime('%Y%m%d_%H%M%S')}.html")

    app_version = app_version or {}
    ver_name    = app_version.get("name", "?")
    ver_code    = app_version.get("code", "?")

    crashes    = summary.get("crashes", 0)
    peak_mem   = summary.get("peak_mem_mb", 0)
    baseline   = summary.get("baseline_mem_mb", 0)
    duration   = summary.get("duration_str", "—")
    anrs       = summary.get("anrs", 0)
    net_fails  = summary.get("net_failures", 0)
    focus_iss  = summary.get("focus_issues", 0)
    frame_drps = summary.get("frame_drops", 0)
    screenshots= summary.get("screenshots", 0)
    screens    = summary.get("screens_visited", [])
    steps      = summary.get("steps", [])
    net_errors = summary.get("net_errors", [])
    focus_evts = summary.get("focus_events", [])
    timeline   = summary.get("timeline", [])
    unique_cr  = summary.get("unique_crashes", crashes)
    leak       = summary.get("leak_detected", False)
    peak_cpu   = summary.get("peak_cpu", 0)
    avg_cpu    = summary.get("avg_cpu", 0)
    cpu_samp   = summary.get("cpu_samples", [])
    batt_start = summary.get("battery_start", 0)
    batt_end   = summary.get("battery_end", 0)
    batt_drain = summary.get("battery_drain", 0)
    drain_hr   = summary.get("drain_per_hour", 0)
    temp_peak  = summary.get("temp_peak", 0)
    rec_times  = summary.get("recovery_times", [])
    avg_rec    = summary.get("avg_recovery_sec", 0)
    qa_score   = summary.get("qa_score", 0)

    stability       = "STABLE" if crashes == 0 and anrs == 0 else \
                      "UNSTABLE" if crashes <= 2 else "CRITICAL"
    stability_color = {"STABLE":"#4caf50","UNSTABLE":"#ff9800","CRITICAL":"#e50914"}[stability]

    score_color = "#4caf50" if qa_score >= 80 else "#ff9800" if qa_score >= 50 else "#e50914"
    score_label = "EXCELLENT" if qa_score >= 90 else "GOOD" if qa_score >= 70 else \
                  "NEEDS WORK" if qa_score >= 50 else "CRITICAL"

    # ── Memory data ───────────────────────────────────────────────────────────
    mem_file = os.path.join(session_dir, "memory.txt")
    mem_vals = []
    if os.path.exists(mem_file):
        with open(mem_file) as f:
            for line in f:
                m = line.split("MEM=")
                if len(m) > 1:
                    try: mem_vals.append(float(m[1].split("MB")[0]))
                    except: pass

    # ── Timeline HTML ─────────────────────────────────────────────────────────
    type_styles = {
        "CRASH":      ("#e50914", "💥"),
        "MEMORY":     ("#ff9800", "🟠"),
        "PERF":       ("#ff9800", "⚡"),
        "ANR":        ("#e50914", "🚨"),
        "NETWORK":    ("#ff5722", "🌐"),
        "CONTENT":    ("#ffd600", "⚠️"),
        "FOCUS":      ("#2196f3", "🎯"),
        "SCREENSHOT": ("#4caf50", "📸"),
        "INFO":       ("#555",    "ℹ️"),
        "LOG":        ("#444",    "📋"),
    }
    timeline_html = ""
    for ev in timeline:
        etype  = ev.get("type","INFO")
        color, icon = type_styles.get(etype, ("#555","•"))
        mins   = ev.get("elapsed", 0) // 60
        secs   = ev.get("elapsed", 0) % 60
        timeline_html += f"""
        <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #111;align-items:flex-start;">
          <div style="min-width:70px;text-align:right;font-size:11px;color:#555;padding-top:2px;">{ev.get('time','')}</div>
          <div style="min-width:30px;font-size:14px;text-align:center;">{icon}</div>
          <div style="flex:1;">
            <span style="background:{color}22;color:{color};font-size:10px;font-weight:700;
                         padding:1px 6px;border-radius:8px;margin-right:6px;">{etype}</span>
            <span style="color:#bbb;font-size:13px;">{ev.get('message','')[:100]}</span>
          </div>
          <div style="min-width:50px;text-align:right;font-size:10px;color:#333;">{mins}m{secs:02d}s</div>
        </div>"""

    # ── Steps to reproduce ────────────────────────────────────────────────────
    steps_html = ""
    if steps:
        for i, s in enumerate(steps[-30:], 1):
            steps_html += f'<div style="padding:5px 0;border-bottom:1px solid #111;font-size:12px;color:#888;font-family:monospace;">{i:02d}. {s}</div>'
    else:
        steps_html = '<div style="color:#444;font-size:13px;">No keypress events captured.</div>'

    # ── Network errors ────────────────────────────────────────────────────────
    net_html = ""
    if net_errors:
        for e in net_errors:
            net_html += f"""
            <div style="background:#1a0500;border-left:3px solid #ff5722;border-radius:6px;
                        padding:10px;margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;">
                <span style="color:#ff7043;font-size:12px;font-weight:700;">🌐 Network Error</span>
                <span style="color:#555;font-size:11px;">{e.get('time','')} · {e.get('screen','')}</span>
              </div>
              <div style="color:#aaa;font-size:12px;margin-top:4px;font-family:monospace;">{e.get('error','')}</div>
            </div>"""
    else:
        net_html = '<div style="color:#444;padding:12px;">No network errors detected.</div>'

    # ── Focus events ──────────────────────────────────────────────────────────
    focus_html = ""
    if focus_evts:
        for e in focus_evts:
            focus_html += f'<div style="padding:6px 0;border-bottom:1px solid #111;font-size:12px;color:#888;">🎯 {e}</div>'
    else:
        focus_html = '<div style="color:#444;padding:12px;">No focus issues detected.</div>'

    # ── Screen journey ────────────────────────────────────────────────────────
    screens_html = ""
    for i, s in enumerate(screens):
        arrow = " → " if i < len(screens) - 1 else ""
        screens_html += (
            f'<span style="background:#1a1a2e;border:1px solid #2a2a4e;border-radius:6px;'
            f'padding:4px 10px;font-size:12px;color:#aaa;">{s}</span>'
            + (f'<span style="color:#444;"> → </span>' if arrow else "")
        )

    # ── Recovery times ────────────────────────────────────────────────────────
    recovery_html = ""
    if rec_times:
        for i, t in enumerate(rec_times, 1):
            recovery_html += (
                f'<div style="padding:6px 0;border-bottom:1px solid #111;font-size:13px;color:#aaa;">'
                f'Crash #{i} — app recovered in <strong style="color:#4caf50;">{t}s</strong></div>'
            )
    else:
        recovery_html = '<div style="color:#444;">No crashes recorded.</div>'

    # ── Build comparison ──────────────────────────────────────────────────────
    compare_html = ""
    if compare_data:
        rows = ""
        for m in compare_data.get("metrics", []):
            rows += f"""
            <tr style="border-bottom:1px solid #1a1a2a;">
              <td style="padding:12px 16px;color:#ccc;">{m['name']}</td>
              <td style="padding:12px 16px;text-align:center;color:#aaa;">{m['a']}</td>
              <td style="padding:12px 16px;text-align:center;color:#aaa;">{m['b']}</td>
              <td style="padding:12px 16px;text-align:center;color:{m['color']};font-weight:700;">{m['delta']}</td>
              <td style="padding:12px 16px;text-align:center;">
                <span style="background:{m['color']}22;color:{m['color']};padding:3px 10px;
                             border-radius:10px;font-size:11px;font-weight:700;">{m['verdict']}</span>
              </td>
            </tr>"""
        overall_c = "#4caf50" if compare_data["overall"] == "IMPROVED" else \
                    "#e50914" if compare_data["overall"] == "REGRESSED" else "#888"
        compare_html = f"""
        <div class="section">
          <div class="section-title">🔄 Build Comparison — {compare_data['label_a']} vs {compare_data['label_b']}</div>
          <div style="margin-bottom:16px;">
            <span style="background:{overall_c}22;color:{overall_c};border:1px solid {overall_c};
                         padding:6px 20px;border-radius:20px;font-weight:700;font-size:14px;">
              Overall: {compare_data['overall']}
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <thead>
              <tr style="background:#1a1a2e;color:#666;font-size:11px;text-transform:uppercase;letter-spacing:1px;">
                <th style="padding:10px 16px;text-align:left;">Metric</th>
                <th style="padding:10px 16px;text-align:center;">{compare_data['label_a']}</th>
                <th style="padding:10px 16px;text-align:center;">{compare_data['label_b']}</th>
                <th style="padding:10px 16px;text-align:center;">Change</th>
                <th style="padding:10px 16px;text-align:center;">Status</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    # ── Recordings ────────────────────────────────────────────────────────────
    if recordings:
        rec_cards = ""
        for i, r in enumerate(recordings, 1):
            rel = os.path.relpath(r, os.path.dirname(out_path))
            rec_cards += f"""
            <div style="background:#0f0f1a;border-radius:10px;overflow:hidden;border:1px solid #1e1e2e;">
              <video controls style="width:100%;display:block;background:#000;">
                <source src="{rel}" type="video/mp4">
              </video>
              <div style="padding:8px 12px;font-size:12px;color:#555;">Segment {i} · {os.path.basename(r)}</div>
            </div>"""
        rec_block = f"""
        <div class="section">
          <div class="section-title">🎬 Screen Recordings ({len(recordings)} segments)</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;">
            {rec_cards}
          </div>
        </div>"""
    else:
        rec_block = ""

    # ── Screenshots ───────────────────────────────────────────────────────────
    ss_dir   = os.path.join(session_dir, "screenshots")
    ss_cards = ""
    if os.path.exists(ss_dir):
        imgs = sorted(f for f in os.listdir(ss_dir) if f.endswith(".png"))
        for img in imgs:
            rel    = os.path.relpath(os.path.join(ss_dir, img), os.path.dirname(out_path))
            border = "#e50914" if "crash" in img.lower() or "CRASH" in img else \
                     "#ff9800" if "anr" in img.lower() or "MEM" in img else "#1e1e2e"
            label  = img.replace("_", " ").replace(".png", "")
            ss_cards += f"""
            <div style="background:#0f0f1a;border-radius:8px;overflow:hidden;border:1px solid {border};">
              <img src="{rel}" style="width:100%;display:block;">
              <div style="padding:6px 8px;font-size:10px;color:#555;">{label}</div>
            </div>"""

    # ── AI analyses ───────────────────────────────────────────────────────────
    analyses_block = ""
    if analyses_html:
        analyses_block = f"""
        <div class="section">
          <div class="section-title">🤖 Crash Analysis — 9-Step QA Engine</div>
          {"".join(analyses_html)}
        </div>"""

    alerts_block = ""
    if manual_alerts_html:
        alerts_block = f"""
        <div class="section">
          <div class="section-title">⚡ Real-time Alerts</div>
          {"".join(manual_alerts_html)}
        </div>"""

    # ── CSV export ────────────────────────────────────────────────────────────
    csv_path = os.path.join(session_dir, "events.csv")
    try:
        with open(csv_path, "w", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["time", "elapsed_sec", "type", "message"])
            for ev in timeline:
                writer.writerow([
                    ev.get("time", ""),
                    ev.get("elapsed", ""),
                    ev.get("type", ""),
                    ev.get("message", ""),
                ])
    except:
        pass

    csv_rel = os.path.relpath(csv_path, os.path.dirname(out_path))

    # ── Full HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{app_name} QA Report — {date_str}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{font-family:'Segoe UI',sans-serif;background:#0a0a0f;color:#e0e0e0;}}
  .header{{background:linear-gradient(135deg,#1a0a2e,#0d1117);border-bottom:3px solid #e50914;padding:36px 40px;}}
  .header-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap;}}
  .app-name{{font-size:26px;font-weight:900;color:#fff;}}
  .app-pkg{{font-size:12px;color:#555;margin-top:3px;}}
  .app-ver{{font-size:12px;color:#888;margin-top:2px;}}
  .build-box{{background:#1e3a5f;border:1px solid #2196f3;border-radius:8px;padding:10px 16px;text-align:right;}}
  .build-box .lbl{{font-size:10px;color:#90caf9;text-transform:uppercase;letter-spacing:1px;}}
  .build-box .val{{font-size:13px;font-weight:700;color:#fff;margin-top:2px;}}
  .score-box{{display:flex;flex-direction:column;align-items:center;justify-content:center;
              background:#0f0f1a;border:2px solid {score_color};border-radius:12px;
              padding:12px 24px;min-width:110px;}}
  .score-num{{font-size:42px;font-weight:900;color:{score_color};line-height:1;}}
  .score-lbl{{font-size:10px;color:{score_color};margin-top:4px;text-transform:uppercase;letter-spacing:1px;font-weight:700;}}
  .score-sub{{font-size:9px;color:#555;margin-top:2px;}}
  .report-title{{margin-top:14px;font-size:28px;font-weight:800;color:#fff;}}
  .meta{{margin-top:6px;color:#666;font-size:13px;}}
  .meta span{{margin-right:14px;}}
  .verdict-bar{{display:flex;gap:12px;padding:18px 40px;background:#0f0f1a;border-bottom:1px solid #1a1a2a;flex-wrap:wrap;}}
  .v-card{{flex:1;min-width:90px;background:#1a1a2e;border:1px solid #2a2a3e;border-radius:10px;padding:14px;text-align:center;}}
  .v-card.red{{border-color:#e50914;background:#1a0a0a;}}
  .v-card.orange{{border-color:#ff9800;background:#1a1200;}}
  .v-card.green{{border-color:#4caf50;background:#0a1a0a;}}
  .v-card.blue{{border-color:#2196f3;background:#0a0f1a;}}
  .v-card.purple{{border-color:#9c27b0;background:#0f0a1a;}}
  .v-card.teal{{border-color:#009688;background:#0a1a18;}}
  .v-num{{font-size:28px;font-weight:900;}}
  .v-card.red .v-num{{color:#e50914;}}
  .v-card.orange .v-num{{color:#ff9800;}}
  .v-card.green .v-num{{color:#4caf50;}}
  .v-card.blue .v-num{{color:#2196f3;}}
  .v-card.purple .v-num{{color:#ce93d8;}}
  .v-card.teal .v-num{{color:#4db6ac;}}
  .v-lbl{{font-size:10px;color:#555;margin-top:3px;text-transform:uppercase;letter-spacing:1px;}}
  .v-sub{{font-size:10px;color:#333;margin-top:2px;}}
  .stability-bar{{padding:14px 40px;background:#0a0a0f;border-bottom:1px solid #1a1a2a;
                  display:flex;align-items:center;gap:14px;flex-wrap:wrap;}}
  .stab-pill{{padding:6px 20px;border-radius:20px;font-weight:700;font-size:13px;
              border:2px solid {stability_color};color:{stability_color};background:{stability_color}22;}}
  .leak-pill{{padding:6px 16px;border-radius:20px;font-weight:700;font-size:13px;
              border:2px solid #ff5722;color:#ff5722;background:#ff572222;}}
  .section{{padding:26px 40px;border-bottom:1px solid #1a1a2a;}}
  .section-title{{font-size:17px;font-weight:700;color:#fff;margin-bottom:16px;
                  padding-bottom:8px;border-bottom:2px solid #e50914;}}
  .chart-bars{{display:flex;align-items:flex-end;height:110px;gap:2px;}}
  .bar{{border-radius:2px 2px 0 0;}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
  .grid4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
  .card{{background:#0f0f1a;border:1px solid #1e1e2e;border-radius:8px;padding:14px;}}
  .card .lbl{{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;}}
  .card .val{{font-size:15px;color:#ccc;font-weight:600;}}
  .footer{{padding:18px 40px;text-align:center;color:#333;font-size:12px;border-top:1px solid #1a1a2a;}}
  a{{color:#2196f3;text-decoration:none;}}
  a:hover{{text-decoration:underline;}}
</style>
</head>
<body>

<div class="header">
  <div class="header-row">
    <div>
      <div class="app-name">{app_name}</div>
      <div class="app-pkg">{package}</div>
      <div class="app-ver">v{ver_name} · build {ver_code}</div>
    </div>
    <div class="score-box">
      <div class="score-num">{qa_score}</div>
      <div class="score-lbl">QA Score</div>
      <div class="score-sub">{score_label}</div>
    </div>
    <div class="build-box">
      <div class="lbl">Device</div>
      <div class="val">{device_info.get('brand','')} {device_info.get('model','?')}</div>
      <div class="lbl" style="margin-top:5px;">Android</div>
      <div class="val" style="font-size:12px;">{device_info.get('android','?')} · SDK {device_info.get('sdk','?')}</div>
    </div>
  </div>
  <div class="report-title">QA Test Report</div>
  <div class="meta">
    <span>📅 {date_str}</span>
    <span>⏱ {duration}</span>
    <span>📡 {device_info.get('serial','')}</span>
    <span>🔋 {batt_start}% → {batt_end}% ({batt_drain}% drain)</span>
    <span>🤖 QA Engine v2.1</span>
    <span><a href="{csv_rel}" download>📥 Download CSV</a></span>
  </div>
</div>

<div class="verdict-bar">
  <div class="v-card {'red' if crashes>0 else 'green'}">
    <div class="v-num">{crashes}</div>
    <div class="v-lbl">Crashes</div>
    <div class="v-sub">{unique_cr} unique</div>
  </div>
  <div class="v-card {'orange' if peak_mem > (baseline*1.5 if baseline else 350) else 'green'}">
    <div class="v-num">{peak_mem:.0f}<span style="font-size:14px">MB</span></div>
    <div class="v-lbl">Peak RAM</div>
    <div class="v-sub">baseline {baseline:.0f}MB</div>
  </div>
  <div class="v-card {'orange' if peak_cpu>70 else 'green'}">
    <div class="v-num">{peak_cpu:.0f}<span style="font-size:14px">%</span></div>
    <div class="v-lbl">Peak CPU</div>
    <div class="v-sub">avg {avg_cpu:.0f}%</div>
  </div>
  <div class="v-card {'red' if anrs>0 else 'green'}">
    <div class="v-num">{anrs}</div>
    <div class="v-lbl">ANRs</div>
  </div>
  <div class="v-card {'orange' if net_fails>0 else 'green'}">
    <div class="v-num">{net_fails}</div>
    <div class="v-lbl">Network Errors</div>
  </div>
  <div class="v-card {'orange' if focus_iss>0 else 'green'}">
    <div class="v-num">{focus_iss}</div>
    <div class="v-lbl">Focus Issues</div>
  </div>
  <div class="v-card {'orange' if frame_drps>0 else 'green'}">
    <div class="v-num">{frame_drps}</div>
    <div class="v-lbl">Frame Drops</div>
  </div>
  <div class="v-card teal">
    <div class="v-num">{batt_drain}</div>
    <div class="v-lbl">Battery %</div>
    <div class="v-sub">{drain_hr}%/hr · {temp_peak}°C peak</div>
  </div>
  <div class="v-card blue">
    <div class="v-num">{len(screens)}</div>
    <div class="v-lbl">Screens</div>
  </div>
  <div class="v-card purple">
    <div class="v-num">{screenshots}</div>
    <div class="v-lbl">Screenshots</div>
  </div>
</div>

<div class="stability-bar">
  <div class="stab-pill">{stability}</div>
  {'<div class="leak-pill">⚠️ MEMORY LEAK</div>' if leak else ''}
  <span style="color:#888;font-size:13px;">
    {'No crashes or ANRs. App ran stably for ' + duration + '.' if stability=='STABLE' else
     str(crashes) + ' crash(es), ' + str(anrs) + ' ANR(s) detected in ' + duration + '. Peak RAM: ' + str(peak_mem) + 'MB.'}
    {('  Avg crash recovery: ' + str(avg_rec) + 's.') if rec_times else ''}
  </span>
</div>

<!-- DEVICE -->
<div class="section">
  <div class="section-title">📱 Device & Session Info</div>
  <div class="grid4">
    <div class="card"><div class="lbl">Model</div><div class="val">{device_info.get('model','?')}</div></div>
    <div class="card"><div class="lbl">Brand</div><div class="val">{device_info.get('brand','?')}</div></div>
    <div class="card"><div class="lbl">Android</div><div class="val">{device_info.get('android','?')}</div></div>
    <div class="card"><div class="lbl">Connection</div><div class="val">{device_info.get('serial','?')}</div></div>
    <div class="card"><div class="lbl">App Version</div><div class="val">v{ver_name}</div></div>
    <div class="card"><div class="lbl">Build Code</div><div class="val">{ver_code}</div></div>
    <div class="card"><div class="lbl">Battery Start</div><div class="val">{batt_start}%</div></div>
    <div class="card"><div class="lbl">Peak Temp</div><div class="val">{temp_peak}°C</div></div>
  </div>
</div>

<!-- MEMORY CHART -->
<div class="section">
  <div class="section-title">📈 Memory Timeline {' — ⚠️ Leak Detected' if leak else ''}</div>
  <div style="background:#0d1117;border-radius:12px;padding:20px;border:1px solid #1e2a3a;">
    <div style="display:flex;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:10px;">
      <span style="font-size:12px;color:#555;">Peak: <span style="color:#e50914;">{peak_mem}MB</span></span>
      <span style="font-size:12px;color:#555;">Baseline: <span style="color:#4caf50;">{baseline}MB</span></span>
      <span style="font-size:12px;color:#555;">Warn: <span style="color:#ff9800;">{baseline*1.5:.0f}MB</span></span>
      <span style="font-size:12px;color:#555;">Critical: <span style="color:#e50914;">{baseline*2:.0f}MB</span></span>
      <span style="font-size:12px;color:#555;">Samples: {len(mem_vals)}</span>
    </div>
    <div class="chart-bars" id="memChart"></div>
    <div style="display:flex;gap:16px;margin-top:10px;flex-wrap:wrap;">
      <span style="font-size:11px;color:#555;">🔴 &gt;2x baseline</span>
      <span style="font-size:11px;color:#555;">🟠 &gt;1.5x baseline</span>
      <span style="font-size:11px;color:#555;">🔵 Normal</span>
      <span style="font-size:11px;color:#555;">🟢 Low</span>
    </div>
  </div>
</div>

<!-- CPU CHART -->
<div class="section">
  <div class="section-title">⚡ CPU Timeline — Peak {peak_cpu:.0f}% · Avg {avg_cpu:.0f}%</div>
  <div style="background:#0d1117;border-radius:12px;padding:20px;border:1px solid #1e2a3a;">
    <div class="chart-bars" id="cpuChart" style="height:80px;"></div>
    <div style="display:flex;gap:16px;margin-top:10px;flex-wrap:wrap;">
      <span style="font-size:11px;color:#555;">🔴 &gt;80%</span>
      <span style="font-size:11px;color:#555;">🟠 &gt;50%</span>
      <span style="font-size:11px;color:#555;">🟢 Normal</span>
    </div>
  </div>
</div>

<!-- SCREEN JOURNEY -->
<div class="section">
  <div class="section-title">🗺️ Screen Journey ({len(screens)} screens)</div>
  <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
    {screens_html if screens_html else '<span style="color:#444;">No screen data captured.</span>'}
  </div>
</div>

<!-- EVENT TIMELINE -->
<div class="section">
  <div class="section-title">⏱ Event Timeline ({len(timeline)} events)</div>
  <div style="background:#0d0d1a;border-radius:12px;border:1px solid #1e1e2e;
              padding:16px;max-height:400px;overflow-y:auto;">
    {timeline_html if timeline_html else '<div style="color:#444;padding:16px;">No events recorded.</div>'}
  </div>
</div>

<!-- STEPS TO REPRODUCE -->
<div class="section">
  <div class="section-title">🎮 Steps to Reproduce — Last 30 Actions</div>
  <div style="background:#0d0d1a;border-radius:12px;border:1px solid #1e1e2e;
              padding:16px;max-height:300px;overflow-y:auto;">
    {steps_html}
  </div>
</div>

<!-- CRASH RECOVERY -->
<div class="section">
  <div class="section-title">⏱ Crash Recovery Times</div>
  <div style="background:#0d0d1a;border-radius:10px;border:1px solid #1e1e2e;padding:16px;">
    {recovery_html}
    {'<div style="color:#555;font-size:12px;margin-top:10px;">Average recovery: ' + str(avg_rec) + 's</div>' if rec_times else ''}
  </div>
</div>

<!-- NETWORK ERRORS -->
<div class="section">
  <div class="section-title">🌐 Network Errors ({net_fails})</div>
  {net_html}
</div>

<!-- FOCUS ISSUES -->
<div class="section">
  <div class="section-title">🎯 Focus Issues ({focus_iss})</div>
  <div style="background:#0d0d1a;border-radius:12px;border:1px solid #1e1e2e;padding:16px;">
    {focus_html}
  </div>
</div>

{compare_html}
{analyses_block}
{alerts_block}
{rec_block}

<!-- SCREENSHOTS -->
<div class="section">
  <div class="section-title">📸 Screenshots ({screenshots})</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;">
    {ss_cards if ss_cards else '<div style="color:#444;padding:16px;">No screenshots captured.</div>'}
  </div>
</div>

<div class="footer">
  {app_name} v{ver_name} QA Report · {date_str} · QA Engine v2.1 · {package}
  &nbsp;·&nbsp; <a href="{csv_rel}" download>Download events CSV</a>
</div>

<script>
// Memory chart
(function(){{
  const data     = {json.dumps(mem_vals)};
  const baseline = {baseline or 1};
  const chart    = document.getElementById('memChart');
  if(chart && data.length){{
    const max = Math.max(...data, baseline*2.5, 100);
    data.forEach(v => {{
      const w = document.createElement('div');
      const b = document.createElement('div');
      b.className = 'bar';
      b.style.height = Math.max(2, v/max*100)+'px';
      b.style.flex   = '1';
      b.style.background = v > baseline*2   ? '#e50914' :
                           v > baseline*1.5 ? '#ff9800' :
                           v > 150          ? '#2196f3' : '#4caf50';
      b.title = v+'MB';
      w.style.flex='1';w.style.display='flex';w.style.flexDirection='column';w.style.justifyContent='flex-end';
      w.appendChild(b);chart.appendChild(w);
    }});
  }}
}})();

// CPU chart
(function(){{
  const data  = {json.dumps(cpu_samp)};
  const chart = document.getElementById('cpuChart');
  if(chart && data.length){{
    const max = Math.max(...data, 10);
    data.forEach(v => {{
      const w = document.createElement('div');
      const b = document.createElement('div');
      b.className = 'bar';
      b.style.height = Math.max(2, v/max*100)+'px';
      b.style.flex   = '1';
      b.style.background = v > 80 ? '#e50914' : v > 50 ? '#ff9800' : '#4caf50';
      b.title = v+'%';
      w.style.flex='1';w.style.display='flex';w.style.flexDirection='column';w.style.justifyContent='flex-end';
      w.appendChild(b);chart.appendChild(w);
    }});
  }}
}})();
</script>
</body>
</html>"""

    with open(out_path, "w") as f:
        f.write(html)

    return out_path
