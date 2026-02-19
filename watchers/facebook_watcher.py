"""
facebook_watcher.py - Facebook Messenger Sense Component (Playwright Browser Automation)

Responsibility:
- Connects to Facebook via headless Chromium browser (Playwright)
- Polls the Messenger inbox every CHECK_INTERVAL seconds
- Detects new incoming DMs in conversations
- Creates a structured Markdown file in AI_Employee_Vault/Needs_Action/ for
  each new message so Claude can draft a reply
- Only fetches while pipeline capacity remains (executed_replies + in_flight
  < DAILY_ACTION_LIMIT), preventing reply spam
- Keeps browser open between poll cycles; saves session after each poll

Boundary:
- READ-ONLY scraping of the Messenger inbox — does NOT send messages
- Does NOT reason, plan, approve, or execute actions
- Does NOT trigger the orchestrator directly; communication is file-based only

Assumptions:
- Session file at credentials/facebook_session.json
  (created via browser/facebook_setup.py)
"""

import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from base_watcher import BaseWatcher
from browser.facebook_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    dismiss_overlays,
    parse_inbox_from_page,
    parse_messages_from_page,
    build_inbox_url,
    build_thread_url,
    human_delay,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
CREDENTIALS_DIR = BASE_DIR / "credentials"
SESSION_PATH = CREDENTIALS_DIR / "facebook_session.json"
PROCESSED_PATH = CREDENTIALS_DIR / ".facebook_processed_ids.json"
FACEBOOK_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".facebook_daily_actions.json"

# Pipeline capacity: watcher only fetches while executed_replies + in_flight < limit
DAILY_ACTION_LIMIT = 5
QUOTA_WINDOW_HOURS = 24

CHECK_INTERVAL = 180            # seconds between polls (3 minutes)
MAX_CONSECUTIVE_FAILURES = 3

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "facebook_watcher.log", encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("facebook_watcher")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_filename(text: str, max_len: int = 40) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]', '_', str(text))
    return text.strip("_")[:max_len]


def _message_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# FacebookWatcher
# ---------------------------------------------------------------------------

class FacebookWatcher(BaseWatcher):
    def __init__(self):
        super().__init__(vault_path=str(VAULT_PATH), check_interval=CHECK_INTERVAL)

        # {thread_id: {"last_hash": str, "sender": str}}
        self.processed: dict[str, dict] = {}

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._browser_healthy = False
        self._consecutive_failures = 0

        self._load_processed()
        self._start_browser()

    # -- Browser lifecycle ---------------------------------------------------

    def _start_browser(self):
        if not SESSION_PATH.exists():
            logger.error(
                "Session file not found at %s. "
                "Run 'python browser/facebook_setup.py' to log in first.",
                SESSION_PATH,
            )
            self._browser_healthy = False
            return

        try:
            self._pw = create_playwright_instance()
            self._browser, self._context = launch_browser(
                self._pw, headless=True, session_path=SESSION_PATH,
            )
            self._page = self._context.new_page()

            if check_login_state(self._page):
                logger.info("Browser started and Facebook login verified.")
                self._browser_healthy = True
                self._consecutive_failures = 0
            else:
                logger.warning(
                    "Browser started but login verification failed. "
                    "Session may be expired — run browser/facebook_setup.py again."
                )
                self._browser_healthy = False

        except Exception:
            logger.exception("Failed to start browser")
            self._browser_healthy = False

    def _stop_browser(self):
        for resource, name in [
            (self._browser, "browser"),
            (self._pw, "playwright"),
        ]:
            if resource:
                try:
                    resource.close() if name == "browser" else resource.stop()
                except Exception:
                    pass
        self._browser = None
        self._context = None
        self._page = None
        self._pw = None
        self._browser_healthy = False

    def _restart_browser(self):
        logger.info("Restarting Facebook browser...")
        self._stop_browser()
        human_delay(2.0, 5.0)
        self._start_browser()

    # -- Processed state persistence -----------------------------------------

    def _load_processed(self):
        if PROCESSED_PATH.exists():
            try:
                self.processed = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
                logger.info("Loaded %d processed Facebook thread(s).", len(self.processed))
            except Exception:
                logger.exception("Failed to load processed state; starting fresh.")
                self.processed = {}

    def _save_processed(self):
        PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROCESSED_PATH.write_text(json.dumps(self.processed, indent=2), encoding="utf-8")

    # -- Pipeline capacity ---------------------------------------------------

    def _pipeline_slots_remaining(self) -> int:
        """Return how many new DMs the watcher should fetch this poll."""
        executed_today = 0
        if FACEBOOK_DAILY_ACTIONS_PATH.exists():
            try:
                data = json.loads(FACEBOOK_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
                window_start_str = data.get("window_start_time", "")
                executed_today = data.get("actions_today", 0)
                if window_start_str:
                    window_start = datetime.fromisoformat(window_start_str)
                    if datetime.now() - window_start >= timedelta(hours=QUOTA_WINDOW_HOURS):
                        executed_today = 0
            except Exception:
                logger.debug("Could not read Facebook actions counter; assuming 0.")

        needs_action_dir = Path(self.needs_action)
        pending_dir = VAULT_PATH / "Pending_Approval"
        approved_dir = VAULT_PATH / "Approved"

        in_flight = (
            len(list(needs_action_dir.glob("FACEBOOK_DM_*.md")))
            + len(list(pending_dir.glob("ACTION_FACEBOOK_*.md")))
            + len(list(approved_dir.glob("ACTION_FACEBOOK_*.md")))
        )

        slots = max(0, DAILY_ACTION_LIMIT - executed_today - in_flight)
        logger.info(
            "Facebook pipeline: limit=%d, executed=%d, in_flight=%d → slots=%d",
            DAILY_ACTION_LIMIT, executed_today, in_flight, slots,
        )
        return slots

    # -- DM fetching ---------------------------------------------------------

    def _fetch_new_messages(self) -> list[dict]:
        """Poll the Messenger inbox and return new-message dicts."""
        new_messages = []
        try:
            self._page.goto(build_inbox_url(), wait_until="domcontentloaded", timeout=30_000)
            human_delay(2.5, 4.0)
            dismiss_overlays(self._page)

            conversations = parse_inbox_from_page(self._page, max_conversations=20)
            logger.info("Messenger inbox: found %d conversation(s).", len(conversations))

            for conv in conversations:
                thread_id = conv["thread_id"]
                preview = conv.get("preview_text", "")
                sender = conv.get("sender_text", "unknown")

                preview_hash = _message_hash(preview)
                prev = self.processed.get(thread_id, {})

                if prev.get("last_hash") == preview_hash:
                    logger.debug("Thread %s — no new messages.", thread_id)
                    continue

                logger.info("Thread %s (%s) — new message detected.", thread_id, sender)
                try:
                    self._page.goto(
                        build_thread_url(thread_id),
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    human_delay(2.0, 3.5)
                    dismiss_overlays(self._page)

                    messages = parse_messages_from_page(self._page)

                    incoming = [m for m in messages if m.get("is_incoming")]
                    if not incoming:
                        incoming = messages[-1:] if messages else []

                    if not incoming:
                        logger.warning("Thread %s — could not extract message text.", thread_id)
                        self.processed[thread_id] = {"last_hash": preview_hash, "sender": sender}
                        self._save_processed()
                        continue

                    last_message = incoming[-1]["text"]

                    new_messages.append({
                        "thread_id": thread_id,
                        "thread_url": build_thread_url(thread_id),
                        "sender": sender,
                        "message_text": last_message,
                        "preview_text": preview,
                        "preview_hash": preview_hash,
                    })

                except Exception:
                    logger.exception("Error reading Messenger thread %s", thread_id)

                human_delay(2.0, 3.0)  # polite gap between threads

        except Exception:
            logger.exception("Error polling Messenger inbox")

        return new_messages

    # -- BaseWatcher interface -----------------------------------------------

    def check_for_updates(self) -> list:
        slots = self._pipeline_slots_remaining()
        if slots <= 0:
            logger.info(
                "Skipping fetch — pipeline full or daily limit reached (limit=%d).",
                DAILY_ACTION_LIMIT,
            )
            return []

        if not self._browser_healthy:
            if SESSION_PATH.exists():
                logger.warning("Browser unhealthy — attempting restart.")
                self._restart_browser()
            else:
                logger.warning("No session file. Skipping poll.")
            if not self._browser_healthy:
                return []

        try:
            new_messages = self._fetch_new_messages()

            if len(new_messages) > slots:
                logger.info(
                    "Found %d new DMs but only %d slot(s) available. Capping.",
                    len(new_messages), slots,
                )
                new_messages = new_messages[:slots]

            logger.info(
                "Poll cycle complete — %d new DM(s) queued for pipeline.",
                len(new_messages),
            )

            if self._context:
                save_session(self._context, SESSION_PATH)

            self._consecutive_failures = 0
            return new_messages

        except Exception:
            logger.exception("Error during Facebook poll cycle")
            self._consecutive_failures += 1

            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Browser failed %d times consecutively — restarting.",
                    self._consecutive_failures,
                )
                self._restart_browser()

            return []

    def create_action_file(self, message: dict) -> Path:
        thread_id = message["thread_id"]
        sender = _sanitize_filename(message.get("sender", "unknown"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"FACEBOOK_DM_{timestamp}_{sender}.md"

        msg_text = message.get("message_text", "[No message content]")
        preview = message.get("preview_text", "")

        content = f"""---
type: facebook_dm
source: facebook
thread_id: "{thread_id}"
thread_url: "{message.get('thread_url', '')}"
sender: "{message.get('sender', 'unknown')}"
received_at: "{datetime.now().isoformat()}"
status: pending
---

# Facebook DM from {message.get('sender', 'unknown')}

## Metadata
| Field       | Value |
|-------------|-------|
| Sender      | {message.get('sender', 'unknown')} |
| Thread ID   | {thread_id} |
| Thread URL  | {message.get('thread_url', '')} |
| Detected At | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |

## Message Content
{msg_text}

## Inbox Preview
{preview}

## Raw Reference
- Thread ID: `{thread_id}`
- Thread URL: `{message.get('thread_url', '')}`
"""

        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")

        self.processed[thread_id] = {
            "last_hash": message.get("preview_hash", ""),
            "sender": message.get("sender", "unknown"),
        }
        self._save_processed()

        logger.info("Created: %s", filename)
        return filepath

    def run(self):
        try:
            super().run()
        finally:
            logger.info("Shutting down Facebook browser...")
            self._stop_browser()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("facebook_watcher.py starting — Facebook Messenger Sense Component")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Session: %s", SESSION_PATH)
    logger.info("Poll interval: %ds", CHECK_INTERVAL)
    logger.info(
        "Daily reply limit: %d per %dh (watcher fetches until pipeline full)",
        DAILY_ACTION_LIMIT, QUOTA_WINDOW_HOURS,
    )
    logger.info("=" * 60)

    watcher = FacebookWatcher()
    watcher.run()


if __name__ == "__main__":
    main()
