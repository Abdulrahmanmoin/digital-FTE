"""
linkedin_watcher.py - LinkedIn Sense Component (Playwright Browser Automation)

Responsibility:
- Connects to LinkedIn via headless Chromium browser (Playwright)
- Polls the main LinkedIn feed every CHECK_INTERVAL seconds
- Creates a structured Markdown file in AI_Employee_Vault/Needs_Action/ for
  each detected post containing metadata, content, and engagement context
- Tracks already-processed post IDs to avoid duplicates (persisted to disk)
- Only fetches new posts while pipeline capacity remains (executed_actions +
  in_flight < DAILY_ACTION_LIMIT), ensuring the 24h action cap is respected
- Keeps browser open between poll cycles; saves session state after each poll

Boundary:
- READ-ONLY scraping — does NOT like, comment, or post
- Does NOT reason, plan, approve, or execute actions
- Does NOT trigger the orchestrator directly; communication is file-based only

Assumptions:
- Session file at credentials/linkedin_session.json (created via browser/linkedin_setup.py)
- The vault path is resolved relative to this script's parent directory
"""

import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent dir to path so imports work when run standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from base_watcher import BaseWatcher
from browser.linkedin_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    parse_posts_from_page,
    dismiss_cookie_consent,
    build_feed_url,
    human_delay,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
CREDENTIALS_DIR = BASE_DIR / "credentials"
SESSION_PATH = CREDENTIALS_DIR / "linkedin_session.json"
PROCESSED_IDS_PATH = CREDENTIALS_DIR / ".linkedin_processed_ids.json"
LINKEDIN_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".linkedin_daily_actions.json"

# Pipeline capacity: watcher only fetches posts while executed_actions + in_flight < this limit
DAILY_ACTION_LIMIT = 5
QUOTA_WINDOW_HOURS = 24         # hours in a quota window

CHECK_INTERVAL = 300            # seconds between polls (5 minutes)

# Our own LinkedIn username slug — skip our own posts when scraping
OWN_USERNAME = "arm-test"

# Browser crash recovery threshold
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
        logging.FileHandler(LOG_DIR / "linkedin_watcher.log", encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("linkedin_watcher")


# ---------------------------------------------------------------------------
# Helper: sanitize filenames
# ---------------------------------------------------------------------------

def _sanitize_filename(text: str, max_len: int = 50) -> str:
    """Remove characters unsafe for filenames and truncate."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text)
    return text.strip()[:max_len]


# ---------------------------------------------------------------------------
# LinkedInWatcher
# ---------------------------------------------------------------------------

class LinkedInWatcher(BaseWatcher):
    def __init__(self):
        super().__init__(vault_path=str(VAULT_PATH), check_interval=CHECK_INTERVAL)
        self.processed_ids: dict[str, str] = {}  # post_id -> source

        # Browser state
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._browser_healthy = False
        self._consecutive_failures = 0

        self._load_processed_ids()
        self._start_browser()

    # -- Browser lifecycle ----------------------------------------------------

    def _start_browser(self):
        """Start the Playwright browser with session restore."""
        if not SESSION_PATH.exists():
            logger.error(
                "Session file not found at %s. "
                "Run 'python browser/linkedin_setup.py' to log in first.",
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
                logger.info("Browser started and LinkedIn login verified.")
                self._browser_healthy = True
                self._consecutive_failures = 0
            else:
                logger.warning(
                    "Browser started but login verification failed. "
                    "Session may be expired — run browser/linkedin_setup.py again."
                )
                self._browser_healthy = False

        except Exception:
            logger.exception("Failed to start browser")
            self._browser_healthy = False

    def _stop_browser(self):
        """Close the browser and Playwright."""
        for resource, name in [
            (self._browser, "browser"),
            (self._pw, "playwright"),
        ]:
            if resource:
                try:
                    if name == "browser":
                        resource.close()
                    else:
                        resource.stop()
                except Exception:
                    logger.debug("Error closing %s", name)
        self._browser = None
        self._context = None
        self._page = None
        self._pw = None
        self._browser_healthy = False

    def _restart_browser(self):
        """Stop and restart the browser (crash recovery)."""
        logger.info("Restarting browser...")
        self._stop_browser()
        human_delay(2.0, 5.0)
        self._start_browser()

    # -- Pipeline capacity check ----------------------------------------------

    def _pipeline_slots_remaining(self) -> int:
        """Return how many new posts the watcher should fetch this poll.

        Logic: only fetch while (executed_actions_today + in_flight) < DAILY_ACTION_LIMIT.
        - executed_actions_today: read from the shared .linkedin_daily_actions.json
        - in_flight: files currently in Needs_Action + Pending_Approval + Approved
          that are LinkedIn posts/actions (haven't been executed yet)

        This means the watcher automatically stops when the pipeline is full and
        resumes fetching once executed actions free up capacity.
        """
        # 1. Read executed actions today from shared orchestrator counter
        executed_today = 0
        if LINKEDIN_DAILY_ACTIONS_PATH.exists():
            try:
                data = json.loads(LINKEDIN_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
                window_start_str = data.get("window_start_time", "")
                executed_today = data.get("actions_today", 0)
                # If the 24h window has expired, treat count as 0
                if window_start_str:
                    window_start = datetime.fromisoformat(window_start_str)
                    if datetime.now() - window_start >= timedelta(hours=QUOTA_WINDOW_HOURS):
                        executed_today = 0
            except Exception:
                logger.debug("Could not read LinkedIn actions counter; assuming 0 executed.")

        # 2. Count in-flight files across the pipeline
        needs_action_dir = Path(self.needs_action)
        pending_dir = VAULT_PATH / "Pending_Approval"
        approved_dir = VAULT_PATH / "Approved"

        in_flight = (
            len(list(needs_action_dir.glob("LINKEDIN_POST_*.md")))
            + len(list(pending_dir.glob("ACTION_LINKEDIN_*.md")))
            + len(list(approved_dir.glob("ACTION_LINKEDIN_*.md")))
        )

        slots = DAILY_ACTION_LIMIT - executed_today - in_flight
        slots = max(0, slots)

        logger.info(
            "Pipeline capacity: limit=%d, executed=%d, in_flight=%d → slots_available=%d",
            DAILY_ACTION_LIMIT, executed_today, in_flight, slots,
        )
        return slots

    # -- Processed ID persistence ---------------------------------------------

    def _load_processed_ids(self):
        if PROCESSED_IDS_PATH.exists():
            try:
                data = json.loads(PROCESSED_IDS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.processed_ids = data.get("processed", {})
                else:
                    self.processed_ids = {str(pid): "legacy" for pid in data}
                logger.info("Loaded %d processed LinkedIn post IDs.", len(self.processed_ids))
            except Exception:
                logger.exception("Failed to load processed IDs; starting fresh.")
                self.processed_ids = {}

    def _save_processed_ids(self):
        PROCESSED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"processed": self.processed_ids}
        PROCESSED_IDS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- Feed fetching via browser --------------------------------------------

    def _fetch_feed_posts(self) -> list[dict]:
        """Navigate to the LinkedIn feed and scrape new posts."""
        posts = []
        try:
            url = build_feed_url()
            logger.debug("Navigating to LinkedIn feed: %s", url)
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            human_delay(3.0, 5.0)

            dismiss_cookie_consent(self._page)

            raw = parse_posts_from_page(self._page, max_posts=20)
            for post in raw:
                pid = post.get("id", "")
                if not pid or pid in self.processed_ids:
                    continue
                # Skip our own posts
                if post.get("author_username", "").lower() == OWN_USERNAME.lower():
                    continue

                posts.append({
                    "id": pid,
                    "urn": post.get("urn", f"urn:li:activity:{pid}"),
                    "text": post.get("text", ""),
                    "author_username": post.get("author_username", "unknown"),
                    "author_name": post.get("author_name", "Unknown"),
                    "created_at": post.get("timestamp", ""),
                    "source": "feed",
                })

            if posts:
                logger.info("Scraped %d new post(s) from LinkedIn feed.", len(posts))

        except Exception:
            logger.exception("Error scraping LinkedIn feed page")

        return posts

    # -- BaseWatcher interface ------------------------------------------------

    def check_for_updates(self) -> list:
        """Fetch LinkedIn feed posts, deduplicated, pipeline-capacity-capped."""
        slots = self._pipeline_slots_remaining()
        if slots <= 0:
            logger.info(
                "Skipping fetch — pipeline full or daily limit reached "
                "(limit=%d, no free slots).", DAILY_ACTION_LIMIT,
            )
            return []

        if not self._browser_healthy:
            if SESSION_PATH.exists():
                logger.warning("Browser unhealthy — attempting restart.")
                self._restart_browser()
            else:
                logger.warning("Browser unhealthy and no session file. Skipping poll.")
            if not self._browser_healthy:
                return []

        try:
            all_posts = self._fetch_feed_posts()

            # Deduplicate by post ID
            seen: set[str] = set()
            unique: list[dict] = []
            for p in all_posts:
                if p["id"] not in seen:
                    seen.add(p["id"])
                    unique.append(p)

            # Cap to available pipeline slots
            if len(unique) > slots:
                logger.info(
                    "Found %d posts but only %d pipeline slot(s) available. Capping.",
                    len(unique), slots,
                )
                unique = unique[:slots]

            logger.info(
                "Poll cycle complete — %d new post(s) queued for pipeline.",
                len(unique),
            )

            if self._context:
                save_session(self._context, SESSION_PATH)

            self._consecutive_failures = 0
            return unique

        except Exception:
            logger.exception("Error during LinkedIn browser polling cycle")
            self._consecutive_failures += 1

            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Browser failed %d times consecutively — restarting.",
                    self._consecutive_failures,
                )
                self._restart_browser()

            return []

    def create_action_file(self, post: dict) -> Path:
        """Create a structured Markdown file in Needs_Action/ for a LinkedIn post."""
        pid = post["id"]
        author = _sanitize_filename(post.get("author_username", "unknown"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"LINKEDIN_POST_{timestamp}_{author}.md"

        content = f"""---
type: linkedin_post
source: linkedin
post_id: "{pid}"
post_urn: "{post.get('urn', f'urn:li:activity:{pid}')}"
author_username: "{post.get('author_username', 'unknown')}"
author_name: "{post.get('author_name', 'Unknown')}"
detection_source: "{post.get('source', 'feed')}"
created_at: "{post.get('created_at', '')}"
received_at: "{datetime.now().isoformat()}"
status: pending
---

# LinkedIn Post from {post.get('author_name', 'Unknown')}

## Metadata
| Field           | Value |
|-----------------|-------|
| Author          | {post.get('author_name', 'Unknown')} (@{post.get('author_username', 'unknown')}) |
| Post ID         | {pid} |
| URN             | {post.get('urn', f'urn:li:activity:{pid}')} |
| Source          | {post.get('source', 'feed')} |
| Created         | {post.get('created_at', 'N/A')} |

## Post Content
{post.get('text', '[No content]')}

## Raw Reference
- Post ID: `{pid}`
- URN: `{post.get('urn', f'urn:li:activity:{pid}')}`
- Detection source: `{post.get('source', 'feed')}`
"""

        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")

        self.processed_ids[pid] = post.get("source", "feed")
        self._save_processed_ids()

        return filepath

    def run(self):
        """Override run() to ensure browser cleanup on exit."""
        try:
            super().run()
        finally:
            logger.info("Shutting down LinkedIn browser...")
            self._stop_browser()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("linkedin_watcher.py starting — LinkedIn Sense Component (Playwright)")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Session: %s", SESSION_PATH)
    logger.info("Poll interval: %ds", CHECK_INTERVAL)
    logger.info(
        "Daily action limit: %d engagements per %d hours (watcher fetches until pipeline full)",
        DAILY_ACTION_LIMIT, QUOTA_WINDOW_HOURS,
    )
    logger.info("=" * 60)

    watcher = LinkedInWatcher()
    watcher.run()


if __name__ == "__main__":
    main()
