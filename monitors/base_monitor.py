"""
Base class for all monitors.
"""

import logging
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseMonitor(ABC):
    """
    Abstract base class for all monitoring components.
    Each monitor runs in its own thread and posts IssueEvents
    to the shared event queue.
    """

    def __init__(self, session):
        """
        session: SessionManager instance providing:
            - session.event_queue  (queue.Queue)
            - session.stop_event   (threading.Event)
            - session.adb          (ADBClient)
            - session.app          (AppController)
        """
        self._session = session
        self._queue = session.event_queue
        self._stop = session.stop_event
        self._adb = session.adb
        self._app = session.app
        self._log = logging.getLogger(self.__class__.__name__)

    def emit(self, event):
        """Push an issue event to the central queue."""
        self._queue.put(event)
        self._log.debug(f"Event emitted: {event}")

    @abstractmethod
    def run(self):
        """Monitor entry point — called in a dedicated thread."""
        ...
