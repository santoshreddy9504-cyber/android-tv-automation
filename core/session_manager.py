"""
Session Manager — orchestrates the full monitoring lifecycle.
Starts all monitors, routes events to handlers, manages shutdown.
"""

import logging
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import List, Optional

from config import config
from models.events import IssueEvent, IssueCategory, SessionStats
from core.adb_client import ADBClient
from core.app_controller import AppController

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Central coordinator for a monitoring session.

    Usage:
        session = SessionManager()
        session.start()          # blocks until session ends
        report = session.stats   # access post-session report
    """

    def __init__(self):
        self._adb = ADBClient()
        self._app = AppController(self._adb)
        self._event_queue: queue.Queue[IssueEvent] = queue.Queue()
        self._monitors: list = []
        self._handlers: list = []
        self._stop_event = threading.Event()
        self._session_id = str(uuid.uuid4())[:8]
        self._stats = SessionStats(
            session_id=self._session_id,
            start_time=datetime.now(),
        )
        self._performance_history: list = []
        self._dashboard = None

    @property
    def adb(self) -> ADBClient:
        return self._adb

    @property
    def app(self) -> AppController:
        return self._app

    @property
    def stats(self) -> SessionStats:
        return self._stats

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def event_queue(self) -> queue.Queue:
        return self._event_queue

    @property
    def session_id(self) -> str:
        return self._session_id

    def register_monitor(self, monitor):
        """Register a monitor to be started with the session."""
        self._monitors.append(monitor)

    def register_handler(self, handler):
        """Register an event handler."""
        self._handlers.append(handler)

    def set_dashboard(self, dashboard):
        self._dashboard = dashboard

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """
        Main entry point. Blocks until the session ends (duration
        reached, user interrupt, or unrecoverable failure).
        """
        logger.info(f"=== Session {self._session_id} starting ===")

        # 1. Connect to device
        if not self._adb.connect():
            logger.critical("Cannot connect to device. Aborting.")
            return

        # 2. Print device info
        info = self._adb.get_device_info()
        logger.info(
            f"Device: {info.get('manufacturer', '?')} {info.get('model', '?')} "
            f"| Android {info.get('android_version', '?')} "
            f"| RAM: {info.get('total_memory_mb', 0):.0f} MB"
        )

        # 3. Launch app
        if not self._app.launch():
            logger.error("App launch failed. Continuing to monitor anyway...")

        # 4. Start event dispatcher thread
        dispatcher = threading.Thread(
            target=self._dispatch_events,
            name="EventDispatcher",
            daemon=True,
        )
        dispatcher.start()

        # 5. Start all monitors
        monitor_threads = []
        for monitor in self._monitors:
            t = threading.Thread(
                target=monitor.run,
                name=monitor.__class__.__name__,
                daemon=True,
            )
            t.start()
            monitor_threads.append(t)
            logger.info(f"Started monitor: {monitor.__class__.__name__}")

        # 6. Start dashboard
        if self._dashboard:
            dash_thread = threading.Thread(
                target=self._dashboard.run,
                name="Dashboard",
                daemon=True,
            )
            dash_thread.start()

        logger.info(
            f"Monitoring {config.app.package_name} | "
            f"Session: {self._session_id} | "
            f"Duration: {config.monitor.session_duration_hours}h"
        )

        # 7. Main loop — wait for duration or stop signal
        try:
            self._wait_for_completion()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt — stopping session")

        # 8. Shutdown
        self._shutdown()

    def _wait_for_completion(self):
        """Block until session duration elapsed or stop_event set."""
        duration_hours = config.monitor.session_duration_hours
        if duration_hours > 0:
            end_time = time.time() + duration_hours * 3600
            while not self._stop_event.is_set():
                remaining = end_time - time.time()
                if remaining <= 0:
                    logger.info("Session duration reached. Stopping.")
                    break
                time.sleep(min(remaining, 5))
        else:
            # Run indefinitely
            self._stop_event.wait()

    def _shutdown(self):
        """Signal all threads to stop and clean up."""
        logger.info("Shutting down session ...")
        self._stop_event.set()

        # Give monitors time to exit
        time.sleep(2)

        self._adb.stop_logcat()
        self._stats.end_time = datetime.now()

        logger.info(
            f"Session ended. Duration: {self._stats.duration_seconds:.0f}s | "
            f"Issues: {self._stats.total_issues} | "
            f"Crashes: {self._stats.crash_count}"
        )

        self._adb.disconnect()

    def stop(self):
        """Externally signal session to stop."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    def _dispatch_events(self):
        """
        Drain the event queue and fan-out to all registered handlers.
        Also updates session statistics and handles crash restarts.
        """
        while not self._stop_event.is_set() or not self._event_queue.empty():
            try:
                event: IssueEvent = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Update session stats
            self._stats.record_event(event)

            # Fan-out to handlers
            for handler in self._handlers:
                try:
                    handler.handle(event, self._adb)
                except Exception as exc:
                    logger.error(f"Handler {handler.__class__.__name__} error: {exc}")

            # Auto-restart on crash
            if event.category == IssueCategory.CRASH:
                restart_thread = threading.Thread(
                    target=self._handle_crash_restart,
                    args=(event,),
                    daemon=True,
                )
                restart_thread.start()

            self._event_queue.task_done()

    def _handle_crash_restart(self, event: IssueEvent):
        """Restart app after a crash event."""
        time.sleep(3)  # Wait for crash dialog to appear
        if self._app.restart(reason=event.title):
            self._stats.restart_count += 1
        else:
            logger.error("Auto-restart failed — stopping session")
            self.stop()

    # ------------------------------------------------------------------
    # Performance data recording (called by PerformanceMonitor)
    # ------------------------------------------------------------------

    def record_performance(self, snapshot):
        """Store a performance snapshot and update rolling averages."""
        self._performance_history.append(snapshot)

        # Update averages
        n = len(self._performance_history)
        self._stats.avg_cpu = sum(
            s.cpu_percent for s in self._performance_history
        ) / n
        self._stats.avg_memory_mb = sum(
            s.memory_mb for s in self._performance_history
        ) / n
        self._stats.peak_cpu = max(
            s.cpu_percent for s in self._performance_history
        )
        self._stats.peak_memory_mb = max(
            s.memory_mb for s in self._performance_history
        )

    def get_latest_performance(self) -> Optional[object]:
        if self._performance_history:
            return self._performance_history[-1]
        return None
