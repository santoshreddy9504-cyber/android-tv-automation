"""
Web Dashboard (optional) — Flask-based dashboard accessible at http://localhost:8080
Provides real-time JSON API and a simple single-page HTML UI.
"""

import json
import logging
import threading
from datetime import datetime
from typing import Optional

from config import config
from models.events import SessionStats

logger = logging.getLogger(__name__)

try:
    from flask import Flask, jsonify, render_template_string, Response
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mission Control — Android TV Monitor</title>
<style>
  :root {
    --bg: #06080f;
    --panel: #0d111d;
    --accent: #4e7cfe;
    --text: #c0c6d8;
    --header-bg: rgba(13, 17, 29, 0.85);
    --warn: #ff9944;
    --err: #ff4444;
    --ok: #22cc66;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Outfit', 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  header { 
    background: var(--header-bg); 
    padding: 24px 48px; 
    border-bottom: 1px solid #1e253c; 
    display: flex; 
    align-items: center; 
    justify-content: space-between;
    position: sticky; top: 0; z-index: 100; backdrop-filter: blur(10px);
  }
  #status-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 10px var(--ok); animation: glow 2s infinite; }
  @keyframes glow { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(1.1); } }
  .container { max-width: 1400px; margin: 0 auto; padding: 40px 48px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 40px; }
  .card { 
    background: var(--panel); border-radius: 16px; padding: 24px; 
    border: 1px solid #1e253c; transition: transform 0.2s, border-color 0.2s;
  }
  .card:hover { transform: translateY(-4px); border-color: var(--accent); }
  .card-val { font-size: 2.2em; font-weight: 800; color: #fff; margin-bottom: 8px; }
  .card-label { color: #5a648a; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 600; }
  
  .section-title { font-size: 0.9em; color: var(--accent); text-transform: uppercase; letter-spacing: 2px; margin: 48px 0 20px; font-weight: 700; display: flex; align-items: center; gap: 12px; }
  .section-title::after { content: ""; flex: 1; height: 1px; background: #1e253c; }
  
  .panels-container { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
  @media (max-width: 1000px) { .panels-container { grid-template-columns: 1fr; } }
  
  .panel { background: var(--panel); border-radius: 16px; padding: 24px; border: 1px solid #1e253c; overflow: hidden; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
  th { padding: 12px; text-align: left; color: #5a648a; font-size: 0.7em; text-transform: uppercase; background: #0b0e1a; }
  td { padding: 12px; border-top: 1px solid #1e253c; }
  tr:hover td { background: #12182d; }
  .badge { padding: 2px 10px; border-radius: 12px; font-size: 0.75em; font-weight: 700; text-transform: uppercase; }
  .tag-pass { color: var(--ok); background: #22cc6615; border: 1px solid #22cc6630; }
  .tag-err { color: var(--err); background: #ff444415; border: 1px solid #ff444430; }
  .tag-slow { color: var(--warn); background: #ff994415; border: 1px solid #ff994430; }
  
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: #1e253c; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:16px">
    <div id="status-dot"></div>
    <h1 style="background:linear-gradient(to right, #fff, #7b9fff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Mission Control</h1>
  </div>
  <div style="font-size:0.85em;color:#5a648a">App: <strong style="color:var(--accent)">{{ package }}</strong></div>
</header>

<div class="container">
  <div class="grid">
    <div class="card"><div class="card-val" id="m-dur">0.0</div><div class="card-label">Run Duration (m)</div></div>
    <div class="card" style="border-top-color:var(--ok)"><div class="card-val" id="m-restarts">0</div><div class="card-label">Restarts</div></div>
    <div class="card" style="border-top-color:var(--err)"><div class="card-val" id="m-crashes">0</div><div class="card-label">Crashes</div></div>
    <div class="card" style="border-top-color:var(--accent)"><div class="card-val" id="m-cpu">0.0</div><div class="card-label">CPU %</div></div>
    <div class="card" style="border-top-color:var(--accent)"><div class="card-val" id="m-mem">0</div><div class="card-label">RAM (MB)</div></div>
  </div>

  <div class="panels-container">
    <div class="panel">
      <div class="section-title">🕒 Timing Inspector</div>
      <table id="timing-table">
        <thead><tr><th>Category</th><th>Status</th><th>Event</th><th>SLA</th></tr></thead>
        <tbody><tr><td colspan="4" style="text-align:center;color:#444">Waiting for signals...</td></tr></tbody>
      </table>
    </div>
    
    <div class="panel">
      <div class="section-title">🌐 API Monitor</div>
      <table id="api-table">
        <thead><tr><th>Status</th><th>Time</th><th>Method</th><th>URL</th></tr></thead>
        <tbody><tr><td colspan="4" style="text-align:center;color:#444">No traffic yet...</td></tr></tbody>
      </table>
    </div>
  </div>

  <div class="section-title">🚨 Recent Issue Events</div>
  <div class="panel">
    <table id="events-table">
      <thead><tr><th>Timestamp</th><th>Category</th><th>Severity</th><th>Title</th><th>Message</th></tr></thead>
      <tbody><tr><td colspan="5" style="text-align:center;color:#444">System stable — scanning logcat...</td></tr></tbody>
    </table>
  </div>
</div>

<script>
async function poll() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('m-dur').textContent = (d.duration_seconds / 60).toFixed(1);
    document.getElementById('m-restarts').textContent = d.restart_count;
    document.getElementById('m-crashes').textContent = d.crash_count;
    document.getElementById('m-cpu').textContent = d.avg_cpu.toFixed(1);
    document.getElementById('m-mem').textContent = d.avg_memory_mb.toFixed(0);

    // Events Table
    const events = d.recent_events || [];
    const etBody = document.querySelector('#events-table tbody');
    if (events.length > 0) {
      etBody.innerHTML = events.slice().reverse().map(e => `
        <tr>
          <td style="color:#5a648a">${(e.timestamp||'').substring(11,19)}</td>
          <td><span class="badge" style="background:#1e253c;color:#7b9fff">${e.category}</span></td>
          <td><span class="badge ${e.severity === 'CRITICAL' || e.severity === 'HIGH' ? 'tag-err' : 'tag-pass'}">${e.severity}</span></td>
          <td style="color:#fff;font-weight:600">${e.title}</td>
          <td style="max-width:400px;text-overflow:ellipsis;overflow:hidden;white-space:nowrap">${e.message}</td>
        </tr>`).join('');
    }
  } catch(e) {}
}
poll();
setInterval(poll, 2500);
</script>
</body>
</html>"""


class WebDashboard:
    """
    Optional Flask web dashboard.
    Exposes /api/status and a single-page UI at /.
    """

    def __init__(self, session):
        self._session = session
        self._stop = session.stop_event
        self._server: Optional[threading.Thread] = None
        self._recent_events = []
        self._max_recent = 50

    def on_event(self, event):
        """Notify dashboard of a new issue event."""
        self._recent_events.append(event.to_dict())
        if len(self._recent_events) > self._max_recent:
            self._recent_events.pop(0)

    def run(self):
        if not _FLASK_AVAILABLE or not config.dashboard.web_dashboard_enabled:
            return

        app = Flask(__name__)
        session_ref = self._session
        events_ref = self._recent_events

        @app.route("/")
        def index():
            return render_template_string(
                _HTML_TEMPLATE,
                package=config.app.package_name,
            )

        @app.route("/api/status")
        def status():
            stats = session_ref.stats
            data = stats.to_dict()
            data["recent_events"] = list(events_ref)
            return jsonify(data)

        @app.route("/api/events")
        def events():
            return jsonify({"events": list(events_ref)})

        logger.info(
            f"Web dashboard at http://{config.dashboard.web_host}:{config.dashboard.web_port}"
        )

        # Disable Flask request logging noise
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        app.run(
            host=config.dashboard.web_host,
            port=config.dashboard.web_port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
