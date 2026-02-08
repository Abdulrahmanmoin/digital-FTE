"""
Base Watcher - Abstract base class for all watcher components.

Responsibility:
- Provides the polling loop structure for long-running watchers
- Manages the Needs_Action output directory
- Enforces a consistent interface: check_for_updates() and create_action_file()

Boundary:
- Does NOT perform reasoning, planning, or action execution
- Subclasses decide what to watch and how to create action files
"""

import time
import logging
import signal
import sys
from abc import ABC, abstractmethod
from pathlib import Path


class BaseWatcher(ABC):
    def __init__(self, vault_path: str, check_interval: int = 120):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.needs_action.mkdir(parents=True, exist_ok=True)
        self.check_interval = check_interval
        self._running = True
        self.logger = logging.getLogger(self.__class__.__name__)

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        self.logger.info("Shutdown signal received (signal %s). Stopping...", signum)
        self._running = False

    @abstractmethod
    def check_for_updates(self) -> list:
        """Check the external source for new items. Return a list of raw items."""
        pass

    @abstractmethod
    def create_action_file(self, item) -> Path:
        """Create a structured Markdown file in Needs_Action/ for a single item."""
        pass

    def run(self):
        self.logger.info(
            "%s started. Polling every %ds. Vault: %s",
            self.__class__.__name__,
            self.check_interval,
            self.vault_path,
        )
        while self._running:
            try:
                updates = self.check_for_updates()
                for item in updates:
                    if not self._running:
                        break
                    try:
                        filepath = self.create_action_file(item)
                        self.logger.info("Created action file: %s", filepath)
                    except Exception:
                        self.logger.exception("Error processing individual item, skipping")
            except Exception:
                self.logger.exception("Error during polling cycle")
            # Sleep in short increments so shutdown signals are responsive
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)
        self.logger.info("%s stopped.", self.__class__.__name__)
