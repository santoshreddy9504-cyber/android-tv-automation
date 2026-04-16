"""
Universal Screen Recorder — auto-segments recordings, pulls to local on stop.
"""
import threading, time, os, subprocess
from datetime import datetime
from typing import Optional, List
from .adb import ADB


class ScreenRecorder:
    """
    Auto-segmented screen recorder.
    Records in 3-minute segments (Fire TV limit), saves all locally.

    Usage:
        rec = ScreenRecorder(adb, out_dir="sessions/current/recordings")
        rec.start()
        # ... testing ...
        files = rec.stop()
    """

    SEGMENT_LIMIT = 170   # seconds per segment (under 180s Fire TV limit)

    def __init__(self, adb: ADB, out_dir: str = "recordings",
                 bitrate: str = "4M"):
        self.adb     = adb
        self.out_dir = out_dir
        self.bitrate = bitrate

        os.makedirs(out_dir, exist_ok=True)

        self._running       = False
        self._segment       = 0
        self._proc: Optional[subprocess.Popen] = None
        self._thread        = None
        self._saved: List[str] = []
        self._remote_paths: List[str] = []

    def start(self) -> bool:
        self._running = True
        self._thread  = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> List[str]:
        self._running = False
        if self._proc:
            self._proc.terminate()
            time.sleep(1)
        # Pull the last segment
        self._pull_last()
        return self._saved

    def mark(self, label: str):
        """Mark a moment in recording (saves a timestamped note)."""
        ts = datetime.now().strftime("%H:%M:%S")
        mark_file = os.path.join(self.out_dir, "markers.txt")
        with open(mark_file, "a") as f:
            f.write(f"{ts} — Segment {self._segment}: {label}\n")

    # ── Internal ─────────────────────────────────────────────────────────

    def _record_loop(self):
        while self._running:
            self._segment += 1
            remote = f"/sdcard/__qa_rec_seg{self._segment}.mp4"
            self._remote_paths.append(remote)

            ts  = datetime.now().strftime("%H%M%S")
            local = os.path.join(self.out_dir, f"seg{self._segment:02d}_{ts}.mp4")

            cmd = (f"adb -s {self.adb.device} shell screenrecord "
                   f"--time-limit {self.SEGMENT_LIMIT} "
                   f"--bit-rate {self.bitrate} {remote}")

            self._proc = subprocess.Popen(cmd, shell=True)
            self._proc.wait()

            if not self._running:
                # Pull this segment then exit
                self.adb.pull_recording(remote, local)
                self._saved.append(local)
                break

            # Segment finished naturally — pull it
            self.adb.pull_recording(remote, local)
            self._saved.append(local)

    def _pull_last(self):
        if self._remote_paths:
            last_remote = self._remote_paths[-1]
            ts    = datetime.now().strftime("%H%M%S")
            local = os.path.join(self.out_dir, f"seg{self._segment:02d}_{ts}_final.mp4")
            if self.adb.pull_recording(last_remote, local):
                if local not in self._saved:
                    self._saved.append(local)

    @property
    def saved_files(self) -> List[str]:
        return self._saved

    @property
    def segment_count(self) -> int:
        return self._segment
