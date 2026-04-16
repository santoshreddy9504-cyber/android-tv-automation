"""
Enhanced Live Web Dashboard — real-time monitoring accessible from any browser.

Features:
  - Real-time updates via Server-Sent Events (SSE) — no WebSocket library needed
  - Beautiful dark-mode UI with live charts
  - Memory trend graph with crash prediction line
  - Live event feed (crashes, warnings, performance)
  - Multi-device panel
  - Accessible from any device on the network: http://<mac-ip>:8080
  - Zero external JS dependencies — pure vanilla JS

Start:
    dashboard = LiveDashboard(session_manager)
    dashboard.start()   # runs on :8080
    # Visit http://192.168.x.x:8080 from any phone/laptop on same WiFi
"""

import json
import logging
import threading
import time
from datetime import datetime
from queue import Queue, Empty
from typing import List, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)


class DashboardState:
    """Shared state for the live dashboard — updated by monitors."""

    def __init__(self):
        self._lock = threading.Lock()
        self.session_id: str = ""
        self.app_name: str = ""
        self.device_name: str = ""
        self.start_time: datetime = datetime.now()

        # Live metrics
        self.crash_count: int = 0
        self.current_memory_mb: float = 0.0
        self.peak_memory_mb: float = 0.0
        self.current_cpu: float = 0.0
        self.frame_drop_pct: float = 0.0
        self.uptime_seconds: float = 0.0

        # History for chart (last 60 readings)
        self.memory_history: List[float] = []
        self.cpu_history: List[float] = []
        self.time_labels: List[str] = []

        # Crash prediction
        self.predicted_crash_in_min: Optional[float] = None
        self.prediction_confidence: float = 0.0

        # Events (last 50)
        self.events: List[dict] = []

        # Multi-device
        self.devices: List[dict] = []

        # UX score
        self.ux_score: float = 0.0
        self.ux_grade: str = "—"

        # Release gate
        self.release_decision: str = "—"

    def update_performance(self, memory_mb: float, cpu: float, frame_drop: float = 0.0):
        with self._lock:
            self.current_memory_mb = memory_mb
            self.peak_memory_mb = max(self.peak_memory_mb, memory_mb)
            self.current_cpu = cpu
            self.frame_drop_pct = frame_drop
            self.uptime_seconds = (datetime.now() - self.start_time).total_seconds()

            ts = datetime.now().strftime("%H:%M:%S")
            self.memory_history.append(memory_mb)
            self.cpu_history.append(cpu)
            self.time_labels.append(ts)

            # Keep last 60 points
            if len(self.memory_history) > 60:
                self.memory_history.pop(0)
                self.cpu_history.pop(0)
                self.time_labels.pop(0)

    def add_event(self, event_type: str, title: str, message: str,
                  severity: str = "info", timestamp: Optional[datetime] = None):
        with self._lock:
            ts = (timestamp or datetime.now()).strftime("%H:%M:%S")
            self.events.insert(0, {
                "type": event_type,
                "title": title,
                "message": message[:200],
                "severity": severity,
                "time": ts,
            })
            if len(self.events) > 50:
                self.events.pop()

            if event_type == "crash":
                self.crash_count += 1

    def record_crash(self, title: str, message: str):
        self.add_event("crash", title, message, severity="critical")

    def to_json(self) -> str:
        with self._lock:
            return json.dumps({
                "session_id": self.session_id,
                "app_name": self.app_name,
                "device_name": self.device_name,
                "uptime": int(self.uptime_seconds),
                "crash_count": self.crash_count,
                "current_memory_mb": round(self.current_memory_mb, 1),
                "peak_memory_mb": round(self.peak_memory_mb, 1),
                "current_cpu": round(self.current_cpu, 1),
                "frame_drop_pct": round(self.frame_drop_pct, 1),
                "memory_history": self.memory_history[-30:],
                "cpu_history": self.cpu_history[-30:],
                "time_labels": self.time_labels[-30:],
                "events": self.events[:20],
                "predicted_crash_in_min": self.predicted_crash_in_min,
                "prediction_confidence": round(self.prediction_confidence, 2),
                "ux_score": round(self.ux_score, 1),
                "ux_grade": self.ux_grade,
                "release_decision": self.release_decision,
                "devices": self.devices,
            })


# Singleton state shared between handler instances
_state = DashboardState()
_sse_clients: List[Queue] = []
_sse_lock = threading.Lock()


def push_update():
    """Push current state to all SSE clients."""
    data = _state.to_json()
    msg = f"data: {data}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QA Live Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d1a; color: #f8f8f2; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }
  .header { background: #1e1e2e; border-bottom: 1px solid #3a3a5c; padding: 16px 24px;
            display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 20px; color: #bd93f9; }
  .live-dot { width: 10px; height: 10px; background: #50fa7b; border-radius: 50%;
              display: inline-block; margin-right: 8px; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.3; } }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          gap: 16px; padding: 20px; }
  .card { background: #1e1e2e; border-radius: 12px; padding: 20px; border: 1px solid #2a2a3e; }
  .card-title { color: #6272a4; font-size: 11px; text-transform: uppercase;
                letter-spacing: 1px; margin-bottom: 8px; }
  .card-value { font-size: 32px; font-weight: bold; color: #f8f8f2; }
  .card-sub { font-size: 12px; color: #6272a4; margin-top: 4px; }
  .crash-card { border-color: #dc2626; }
  .crash-value { color: #ff5555; }
  .warn-value { color: #ffb86c; }
  .good-value { color: #50fa7b; }
  .section { padding: 0 20px 20px; }
  .section-title { color: #bd93f9; font-size: 14px; font-weight: bold;
                   margin-bottom: 12px; padding-bottom: 6px; border-bottom: 1px solid #2a2a3e; }
  .chart-container { background: #1e1e2e; border-radius: 12px; padding: 20px;
                     border: 1px solid #2a2a3e; position: relative; height: 220px; }
  canvas { max-width: 100%; }
  .events-panel { background: #1e1e2e; border-radius: 12px; padding: 16px;
                  border: 1px solid #2a2a3e; max-height: 400px; overflow-y: auto; }
  .event-item { padding: 10px; border-radius: 6px; margin-bottom: 8px;
                border-left: 3px solid #6272a4; font-size: 13px; }
  .event-crash { border-color: #dc2626; background: #1a1020; }
  .event-warning { border-color: #ffb86c; background: #1a1510; }
  .event-info { border-color: #50fa7b; background: #101a12; }
  .event-time { color: #6272a4; font-size: 11px; }
  .event-title { color: #f8f8f2; font-weight: bold; margin-bottom: 2px; }
  .event-msg { color: #8be9fd; font-size: 12px; }
  .prediction-bar { background: #1e1e2e; border-radius: 12px; padding: 16px;
                    border: 2px solid #ca8a04; margin: 0 20px 20px; }
  .hidden { display: none; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
  .badge-go { background: #16a34a; color: white; }
  .badge-nogo { background: #dc2626; color: white; }
  .badge-cond { background: #ca8a04; color: white; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 0 20px 20px; }
  @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } .grid { grid-template-columns: 1fr 1fr; } }
</style>
</head>
<body>

<div class="header">
  <div>
    <span class="live-dot"></span>
    <span class="header h1" style="font-size:20px; color:#bd93f9; font-weight:bold;">QA Live Dashboard</span>
    <span style="color:#6272a4; font-size:13px; margin-left:12px;" id="session-info">Connecting...</span>
  </div>
  <div style="color:#6272a4; font-size:13px;" id="uptime-display">Uptime: —</div>
</div>

<!-- Crash Prediction Banner -->
<div id="prediction-bar" class="prediction-bar hidden">
  <span style="color:#ffb86c; font-weight:bold;">⚠ CRASH PREDICTION: </span>
  <span id="prediction-text" style="color:#f8f8f2;"></span>
</div>

<!-- Metric Cards -->
<div class="grid">
  <div class="card" id="crash-card">
    <div class="card-title">Crashes</div>
    <div class="card-value crash-value" id="crash-count">0</div>
    <div class="card-sub">This session</div>
  </div>
  <div class="card">
    <div class="card-title">Memory</div>
    <div class="card-value" id="memory-val">—</div>
    <div class="card-sub">Peak: <span id="peak-mem">—</span></div>
  </div>
  <div class="card">
    <div class="card-title">CPU</div>
    <div class="card-value" id="cpu-val">—</div>
    <div class="card-sub">Current usage</div>
  </div>
  <div class="card">
    <div class="card-title">Frame Drops</div>
    <div class="card-value" id="frame-val">—</div>
    <div class="card-sub">Janky frames</div>
  </div>
  <div class="card">
    <div class="card-title">UX Score</div>
    <div class="card-value" id="ux-score">—</div>
    <div class="card-sub">Grade: <span id="ux-grade">—</span></div>
  </div>
  <div class="card">
    <div class="card-title">Release Gate</div>
    <div class="card-value" style="font-size:20px; margin-top:6px;" id="release-badge">—</div>
    <div class="card-sub">Build decision</div>
  </div>
</div>

<!-- Charts -->
<div class="two-col">
  <div>
    <div class="section-title" style="margin-left:0; padding:0 0 8px;">Memory Trend</div>
    <div class="chart-container">
      <canvas id="memChart"></canvas>
    </div>
  </div>
  <div>
    <div class="section-title" style="margin-left:0; padding:0 0 8px;">CPU Usage</div>
    <div class="chart-container">
      <canvas id="cpuChart"></canvas>
    </div>
  </div>
</div>

<!-- Events Feed -->
<div class="section">
  <div class="section-title">Live Event Feed</div>
  <div class="events-panel" id="events-panel">
    <div style="color:#6272a4; text-align:center; padding:20px;">Waiting for events...</div>
  </div>
</div>

<script>
// ── Simple canvas chart ───────────────────────────────────────────────
function drawChart(canvasId, data, color, maxVal, label) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !data || data.length === 0) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.parentElement.clientWidth - 40;
  const H = 160;
  canvas.width = W;
  canvas.height = H;
  ctx.clearRect(0, 0, W, H);

  const max = maxVal || Math.max(...data, 1);
  const step = W / Math.max(data.length - 1, 1);

  // Grid lines
  ctx.strokeStyle = '#2a2a3e';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = H - (i / 4) * H;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    ctx.fillStyle = '#6272a4';
    ctx.font = '10px sans-serif';
    ctx.fillText(Math.round((i / 4) * max), 2, y - 2);
  }

  // Fill area
  ctx.beginPath();
  ctx.moveTo(0, H);
  data.forEach((v, i) => {
    const x = i * step;
    const y = H - (v / max) * H;
    if (i === 0) ctx.lineTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.lineTo((data.length - 1) * step, H);
  ctx.closePath();
  ctx.fillStyle = color + '33';
  ctx.fill();

  // Line
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = i * step;
    const y = H - (v / max) * H;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Current value dot
  if (data.length > 0) {
    const lx = (data.length - 1) * step;
    const ly = H - (data[data.length - 1] / max) * H;
    ctx.beginPath();
    ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }

  // Label
  ctx.fillStyle = '#6272a4';
  ctx.font = '11px sans-serif';
  ctx.fillText(label || '', 4, 14);
}

// ── State update ──────────────────────────────────────────────────────
function updateUI(state) {
  // Header
  document.getElementById('session-info').textContent =
    state.app_name + ' — ' + (state.device_name || 'Device');
  const h = Math.floor(state.uptime / 3600);
  const m = Math.floor((state.uptime % 3600) / 60);
  const s = state.uptime % 60;
  document.getElementById('uptime-display').textContent =
    'Uptime: ' + (h>0?h+'h ':'') + (m>0?m+'m ':'') + s + 's';

  // Crash card
  const crashes = state.crash_count;
  document.getElementById('crash-count').textContent = crashes;
  document.getElementById('crash-card').style.borderColor = crashes > 0 ? '#dc2626' : '#2a2a3e';

  // Memory
  const memEl = document.getElementById('memory-val');
  memEl.textContent = state.current_memory_mb.toFixed(0) + 'MB';
  memEl.className = 'card-value ' +
    (state.current_memory_mb > 400 ? 'crash-value' : state.current_memory_mb > 300 ? 'warn-value' : 'good-value');
  document.getElementById('peak-mem').textContent = state.peak_memory_mb.toFixed(0) + 'MB';

  // CPU
  document.getElementById('cpu-val').textContent = state.current_cpu.toFixed(1) + '%';
  // Frame drops
  document.getElementById('frame-val').textContent = state.frame_drop_pct.toFixed(1) + '%';

  // UX Score
  document.getElementById('ux-score').textContent = state.ux_score > 0 ? state.ux_score.toFixed(0) : '—';
  document.getElementById('ux-grade').textContent = state.ux_grade;

  // Release Gate
  const rd = document.getElementById('release-badge');
  if (state.release_decision === 'GO') {
    rd.innerHTML = '<span class="badge badge-go">✅ GO</span>';
  } else if (state.release_decision === 'NO-GO') {
    rd.innerHTML = '<span class="badge badge-nogo">🚫 NO-GO</span>';
  } else if (state.release_decision === 'CONDITIONAL GO') {
    rd.innerHTML = '<span class="badge badge-cond">⚠ COND. GO</span>';
  } else {
    rd.textContent = '—';
  }

  // Prediction banner
  const bar = document.getElementById('prediction-bar');
  if (state.predicted_crash_in_min && state.predicted_crash_in_min < 10) {
    bar.classList.remove('hidden');
    document.getElementById('prediction-text').textContent =
      'Crash predicted in ' + state.predicted_crash_in_min.toFixed(1) + ' min ' +
      '(Memory growing, ' + state.prediction_confidence * 100 + '% confidence)';
  } else {
    bar.classList.add('hidden');
  }

  // Charts
  drawChart('memChart', state.memory_history, '#ff5555', 500, 'Memory (MB)');
  drawChart('cpuChart', state.cpu_history, '#bd93f9', 100, 'CPU (%)');

  // Events feed
  if (state.events && state.events.length > 0) {
    const panel = document.getElementById('events-panel');
    panel.innerHTML = state.events.map(ev => {
      const cls = ev.severity === 'critical' ? 'event-crash' :
                  ev.severity === 'warning' ? 'event-warning' : 'event-info';
      const icon = ev.type === 'crash' ? '💥' : ev.severity === 'warning' ? '⚠' : '✓';
      return '<div class="event-item ' + cls + '">' +
        '<div class="event-time">' + ev.time + '</div>' +
        '<div class="event-title">' + icon + ' ' + ev.title + '</div>' +
        '<div class="event-msg">' + ev.message + '</div>' +
        '</div>';
    }).join('');
  }
}

// ── SSE connection ────────────────────────────────────────────────────
function connect() {
  const evtSource = new EventSource('/events');
  evtSource.onmessage = function(e) {
    try {
      const state = JSON.parse(e.data);
      updateUI(state);
    } catch(err) { console.warn('Parse error:', err); }
  };
  evtSource.onerror = function() {
    setTimeout(connect, 3000);
  };
}

connect();

// Resize charts on window resize
window.addEventListener('resize', () => {
  // Charts will redraw on next data push
});
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the live dashboard."""

    def log_message(self, *args):
        pass  # Suppress default HTTP logs

    def do_GET(self):
        if self.path == "/" or self.path == "/dashboard":
            self._serve_html()
        elif self.path == "/events":
            self._serve_sse()
        elif self.path == "/state":
            self._serve_state()
        elif self.path == "/health":
            self._serve_ok()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        content = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_sse(self):
        """Server-Sent Events endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = Queue()
        with _sse_lock:
            _sse_clients.append(q)

        # Send initial state immediately
        try:
            self.wfile.write(f"data: {_state.to_json()}\n\n".encode())
            self.wfile.flush()
        except Exception:
            pass

        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except Empty:
                    # Heartbeat
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)

    def _serve_state(self):
        data = _state.to_json().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_ok(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


class LiveDashboard:
    """
    Live web dashboard server.

    Usage:
        dashboard = LiveDashboard()
        dashboard.set_session_info("SouthStream", "192.168.2.29:5555", "s001")
        dashboard.start()

        # From monitoring code:
        dashboard.update_performance(memory_mb=380, cpu=45.0)
        dashboard.report_crash("mqt_native_modules crash", "thread died")
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self._host = host
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._push_thread: Optional[threading.Thread] = None

    def set_session_info(self, app_name: str, device: str, session_id: str):
        _state.app_name = app_name
        _state.device_name = device
        _state.session_id = session_id
        _state.start_time = datetime.now()

    def update_performance(self, memory_mb: float, cpu: float, frame_drop: float = 0.0):
        _state.update_performance(memory_mb, cpu, frame_drop)
        push_update()

    def report_crash(self, title: str, message: str):
        _state.record_crash(title, message)
        push_update()

    def report_event(self, title: str, message: str, level: str = "info"):
        _state.add_event(level, title, message, severity=level)
        push_update()

    def update_prediction(self, minutes_until_crash: Optional[float], confidence: float):
        _state.predicted_crash_in_min = minutes_until_crash
        _state.prediction_confidence = confidence
        push_update()

    def update_ux_score(self, score: float, grade: str):
        _state.ux_score = score
        _state.ux_grade = grade
        push_update()

    def update_release_decision(self, decision: str):
        _state.release_decision = decision
        push_update()

    def start(self):
        """Start the dashboard HTTP server in a background thread."""
        try:
            self._server = HTTPServer((self._host, self._port), DashboardHandler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="LiveDashboard",
                daemon=True,
            )
            self._thread.start()

            import socket
            hostname = socket.gethostname()
            try:
                local_ip = socket.gethostbyname(hostname)
            except Exception:
                local_ip = "localhost"

            logger.info(f"Live Dashboard running at http://{local_ip}:{self._port}")
            print(f"\n  🌐 Live Dashboard: http://{local_ip}:{self._port}")
            print(f"     Open from any device on the same WiFi network\n")

        except Exception as exc:
            logger.error(f"Dashboard failed to start: {exc}")

    def stop(self):
        if self._server:
            self._server.shutdown()

    @property
    def state(self) -> DashboardState:
        return _state


def get_dashboard_state() -> DashboardState:
    """Get the singleton dashboard state."""
    return _state
