"""
main_watcher.py - System Supervisor / Watchdog

Responsibility:
- Launches and monitors gmail_watcher.py, x_watcher.py, linkedin_watcher.py, instagram_watcher.py, facebook_watcher.py, odoo_watcher.py, and orchestrator.py as child processes
- Automatically restarts any process that crashes, exits, or becomes unresponsive
- Logs all crashes, restarts, and failures for audit/debugging
- Runs continuously while the PC is on

Usage:
    python main_watcher.py

    Stop with Ctrl+C (SIGINT) or send SIGTERM — all child processes are
    gracefully terminated before exit.

    (PM2 support is available via ecosystem.config.js but is not required.
     Run directly with the command above until PM2 is re-enabled.)

Boundary:
- Does NOT connect to Gmail
- Does NOT read or write task, plan, or approval files
- Does NOT perform reasoning, planning, or action execution
- Purely a process lifecycle manager

Assumptions:
- Python 3.10+ available on PATH (or activate the venv first)
- All child scripts are in known relative paths
- Heartbeat check uses a simple "is process alive" poll
"""

import subprocess
import sys
import time
import signal
import logging
import os
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

MANAGED_PROCESSES = [
    # Priority 1 — Gmail (fastest, API-based, most important)
    {
        "name": "gmail_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "watchers" / "gmail_watcher.py")],
        "restart_delay": 5,
        "max_rapid_restarts": 5,
        "rapid_window": 60,
    },
    # Priority 2 — LinkedIn
    {
        "name": "linkedin_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "watchers" / "linkedin_watcher.py")],
        "restart_delay": 15,
        "max_rapid_restarts": 3,
        "rapid_window": 120,
    },
    # Priority 3 — X/Twitter
    {
        "name": "x_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "watchers" / "x_watcher.py")],
        "restart_delay": 10,
        "max_rapid_restarts": 3,
        "rapid_window": 120,
    },
    # Priority 4 — Instagram
    {
        "name": "instagram_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "watchers" / "instagram_watcher.py")],
        "restart_delay": 15,
        "max_rapid_restarts": 3,
        "rapid_window": 120,
    },
    # Priority 5 — Facebook
    {
        "name": "facebook_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "watchers" / "facebook_watcher.py")],
        "restart_delay": 15,
        "max_rapid_restarts": 3,
        "rapid_window": 120,
    },
    # Priority 6 — Odoo (lowest priority, polls every 10 min)
    {
        "name": "odoo_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "watchers" / "odoo_watcher.py")],
        "restart_delay": 30,       # slow restart — lowest priority
        "max_rapid_restarts": 3,   # conservative
        "rapid_window": 180,
    },
    # Orchestrator — always last so all watchers are up first
    {
        "name": "orchestrator",
        "cmd": [sys.executable, str(BASE_DIR / "orchestrator.py")],
        "restart_delay": 5,
        "max_rapid_restarts": 5,
        "rapid_window": 60,
    },
    # Reporting & Analytics — periodic updates
    {
        "name": "reporting_engine",
        "cmd": [sys.executable, str(BASE_DIR / "reporting_engine.py")],
        "restart_delay": 60,
        "max_rapid_restarts": 3,
        "rapid_window": 300,
    },
    # CEO Daily Briefing
    {
        "name": "ceo_briefing",
        "cmd": [sys.executable, str(BASE_DIR / "ceo_briefing.py")],
        "restart_delay": 60,
        "max_rapid_restarts": 3,
        "rapid_window": 300,
    },
]

HEALTH_CHECK_INTERVAL = 10  # seconds between liveness checks
LOG_DIR = BASE_DIR / "logs"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "main_watcher.log", encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("main_watcher")

# ---------------------------------------------------------------------------
# Process wrapper
# ---------------------------------------------------------------------------


class ManagedProcess:
    """Wraps a subprocess with restart tracking and back-off logic."""

    def __init__(self, config: dict):
        self.name: str = config["name"]
        self.cmd: list = config["cmd"]
        self.restart_delay: int = config.get("restart_delay", 5)
        self.max_rapid_restarts: int = config.get("max_rapid_restarts", 5)
        self.rapid_window: int = config.get("rapid_window", 60)

        self.process: subprocess.Popen | None = None
        self.restart_times: list[float] = []
        self.total_restarts: int = 0
        self.backoff_until: float = 0

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        """Start the subprocess. Returns True on success."""
        try:
            self.process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "[%s] Started (PID %d)", self.name, self.process.pid
            )
            return True
        except Exception:
            logger.exception("[%s] Failed to start", self.name)
            return False

    def stop(self):
        """Gracefully stop the subprocess."""
        if self.process and self.process.poll() is None:
            logger.info("[%s] Sending SIGTERM (PID %d)", self.name, self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("[%s] Force-killing (PID %d)", self.name, self.process.pid)
                self.process.kill()
                self.process.wait()
            logger.info("[%s] Stopped", self.name)

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # -- restart logic -------------------------------------------------------

    def _in_backoff(self) -> bool:
        return time.time() < self.backoff_until

    def _record_restart(self):
        now = time.time()
        self.restart_times.append(now)
        self.total_restarts += 1
        # Trim old timestamps outside the rapid window
        cutoff = now - self.rapid_window
        self.restart_times = [t for t in self.restart_times if t >= cutoff]

    def _should_backoff(self) -> bool:
        return len(self.restart_times) >= self.max_rapid_restarts

    def ensure_running(self):
        """Check if the process is alive; restart if needed with back-off."""
        if self.is_alive():
            return

        if self._in_backoff():
            return  # still in back-off period, skip

        exit_code = self.process.returncode if self.process else "N/A"
        logger.warning(
            "[%s] Process exited (code=%s). Restarting (#%d)...",
            self.name,
            exit_code,
            self.total_restarts + 1,
        )

        self._record_restart()

        if self._should_backoff():
            backoff_seconds = 60
            self.backoff_until = time.time() + backoff_seconds
            logger.error(
                "[%s] Rapid restart threshold hit (%d restarts in %ds). "
                "Backing off for %ds.",
                self.name,
                self.max_rapid_restarts,
                self.rapid_window,
                backoff_seconds,
            )
            return

        time.sleep(self.restart_delay)
        self.start()


# ---------------------------------------------------------------------------
# Main supervisor loop
# ---------------------------------------------------------------------------

_running = True


def _shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received (signal %s). Stopping supervisor...", signum)
    _running = False


def main():
    global _running

    # ---- singleton guard: prevent two main_watcher instances -----------------
    lock_path = BASE_DIR / "main_watcher.lock"
    lock_file = None
    try:
        if lock_path.exists():
            old_pid = int(lock_path.read_text().strip())
            # Check if that process is actually still alive
            try:
                os.kill(old_pid, 0)  # signal 0 = liveness check
                logger.error(
                    "Another main_watcher.py instance is already running "
                    "(PID %d, lockfile %s). Exiting.",
                    old_pid, lock_path,
                )
                sys.exit(1)
            except (OSError, ProcessLookupError):
                pass  # old PID is dead — stale lock, continue
        lock_path.write_text(str(os.getpid()))
        lock_file = lock_path
    except Exception:
        logger.warning("Could not acquire lockfile — proceeding anyway", exc_info=True)
    # --------------------------------------------------------------------------

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("=" * 60)
    logger.info("main_watcher.py starting — System Supervisor")
    logger.info("Managed processes: %s", [p["name"] for p in MANAGED_PROCESSES])
    logger.info("=" * 60)

    managed: list[ManagedProcess] = []
    for cfg in MANAGED_PROCESSES:
        mp = ManagedProcess(cfg)
        mp.start()
        managed.append(mp)

    while _running:
        for mp in managed:
            mp.ensure_running()
        # Sleep in short increments for responsive shutdown
        for _ in range(HEALTH_CHECK_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    # Graceful shutdown of all children
    logger.info("Shutting down all managed processes...")
    for mp in managed:
        mp.stop()

    if lock_file and lock_file.exists():
        try:
            lock_file.unlink()
        except Exception:
            pass

    logger.info("main_watcher.py exited cleanly.")


if __name__ == "__main__":
    main()
