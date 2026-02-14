"""
x_watcher.py - X/Twitter Sense Component (Playwright Browser Automation)

Responsibility:
- Connects to X/Twitter via headless Chromium browser (Playwright)
- Polls for new tweets from a curated watchlist of followed accounts
  (credentials/x_watchlist.json) plus direct @mentions
- Creates a structured Markdown file in AI_Employee_Vault/Needs_Action/ for
  each detected tweet containing metadata, content, and engagement context
- Tracks already-processed tweet IDs to avoid duplicates (persisted to disk)
- Only fetches new tweets while pipeline capacity remains (executed_actions +
  in_flight < DAILY_ACTION_LIMIT), ensuring the 24h action cap is respected
- Keeps browser open between poll cycles; saves session state after each poll

Boundary:
- READ-ONLY scraping — does NOT like, retweet, reply, or post
- Does NOT perform keyword/search scraping — watchlist profiles only
- Does NOT reason, plan, approve, or execute actions
- Does NOT trigger the orchestrator directly; communication is file-based only

Assumptions:
- Session file at credentials/x_session.json (created via browser/x_setup.py)
- Watchlist config at credentials/x_watchlist.json
  Format: [{"username": "handle", "notes": "optional context"}, ...]
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
from browser.x_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    parse_tweets_from_page,
    parse_following_from_page,
    build_following_url,
    build_profile_url,
    build_mentions_url,
    human_delay,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
CREDENTIALS_DIR = BASE_DIR / "credentials"
SESSION_PATH = CREDENTIALS_DIR / "x_session.json"
WATCHLIST_PATH = CREDENTIALS_DIR / "x_watchlist.json"
PROCESSED_IDS_PATH = CREDENTIALS_DIR / ".x_processed_ids.json"
X_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".x_daily_actions.json"

# Pipeline capacity: watcher only fetches tweets while executed_actions + in_flight < this limit
DAILY_ACTION_LIMIT = 5
QUOTA_WINDOW_HOURS = 24         # Hours in a quota window

CHECK_INTERVAL = 180            # seconds between polls (3 minutes)
FOLLOWING_SYNC_INTERVAL_HOURS = 24  # How often to re-sync watchlist from Twitter following

# Our own X/Twitter username (without @) — skip our own tweets when scraping
OWN_USERNAME = "arahmanmoin1"

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
        logging.FileHandler(LOG_DIR / "x_watcher.log", encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("x_watcher")


# ---------------------------------------------------------------------------
# Helper: sanitize filenames
# ---------------------------------------------------------------------------

def _sanitize_filename(text: str, max_len: int = 50) -> str:
    """Remove characters unsafe for filenames and truncate."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text)
    return text.strip()[:max_len]


# ---------------------------------------------------------------------------
# XWatcher
# ---------------------------------------------------------------------------

class XWatcher(BaseWatcher):
    def __init__(self):
        super().__init__(vault_path=str(VAULT_PATH), check_interval=CHECK_INTERVAL)
        self.processed_ids: dict[str, str] = {}  # tweet_id -> source
        self.watchlist: list[dict] = []           # [{"username": ..., "notes": ...}]

        # Following sync tracking
        self.last_following_sync: datetime | None = None

        # Browser state
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._browser_healthy = False
        self._consecutive_failures = 0

        self._load_processed_ids()
        self._start_browser()
        # Sync watchlist from live following list (replaces x_watchlist.json)
        self._sync_watchlist_from_following()
        # Fall back to saved watchlist if sync failed or browser wasn't ready
        if not self.watchlist:
            self._load_watchlist()

    # -- Browser lifecycle ----------------------------------------------------

    def _start_browser(self):
        """Start the Playwright browser with session restore."""
        if not SESSION_PATH.exists():
            logger.error(
                "Session file not found at %s. "
                "Run 'python browser/x_setup.py' to log in first.",
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
                logger.info("Browser started and login verified.")
                self._browser_healthy = True
                self._consecutive_failures = 0
            else:
                logger.warning(
                    "Browser started but login verification failed. "
                    "Session may be expired — run browser/x_setup.py again."
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

    # -- Config loading -------------------------------------------------------

    def _load_watchlist(self):
        """Load the watchlist of accounts to monitor from config file.

        Format: [{"username": "handle", "notes": "optional"}, ...]
        Plain list of strings also accepted: ["handle1", "handle2"]
        """
        if not WATCHLIST_PATH.exists():
            logger.warning(
                "Watchlist file not found at %s. No profiles to watch.",
                WATCHLIST_PATH,
            )
            self.watchlist = []
            return

        try:
            raw = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
            # Normalise: accept both [{"username": ...}] and ["username", ...]
            normalised = []
            for entry in raw:
                if isinstance(entry, str):
                    normalised.append({"username": entry, "notes": ""})
                elif isinstance(entry, dict) and "username" in entry:
                    normalised.append(entry)
                else:
                    logger.warning("Skipping invalid watchlist entry: %s", entry)
            self.watchlist = normalised
            usernames = [e["username"] for e in self.watchlist]
            logger.info(
                "Loaded %d watchlist account(s): %s",
                len(self.watchlist),
                ", ".join(f"@{u}" for u in usernames),
            )
        except Exception:
            logger.exception("Failed to load watchlist; using empty list.")
            self.watchlist = []

    # -- Following → watchlist sync -------------------------------------------

    def _sync_watchlist_from_following(self):
        """Scrape the /following page and save all followed accounts to x_watchlist.json.

        Preserves any manually-added 'notes' for accounts that already exist
        in the watchlist. New accounts are added with an empty notes field.
        Removes accounts that are no longer followed.
        """
        if not self._browser_healthy:
            logger.warning("Browser not healthy — skipping following sync.")
            return

        logger.info("Syncing watchlist from Twitter following list (@%s)...", OWN_USERNAME)
        try:
            url = build_following_url(OWN_USERNAME)
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            human_delay(3.0, 5.0)

            following = parse_following_from_page(self._page)

            if not following:
                logger.warning("No accounts returned from following page — skipping save.")
                return

            # Build lookup of existing notes so they're not lost on refresh
            existing_notes: dict[str, str] = {
                e["username"].lower(): e.get("notes", "")
                for e in self.watchlist
            }

            new_watchlist = [
                {
                    "username": entry["username"],
                    "display_name": entry.get("display_name", ""),
                    "notes": existing_notes.get(entry["username"].lower(), ""),
                }
                for entry in following
                if entry.get("username")
            ]

            WATCHLIST_PATH.write_text(
                json.dumps(new_watchlist, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self.watchlist = new_watchlist
            self.last_following_sync = datetime.now()

            logger.info(
                "Watchlist synced: %d account(s) saved to %s",
                len(new_watchlist), WATCHLIST_PATH,
            )

        except Exception:
            logger.exception("Error syncing watchlist from following page")

    def _should_sync_following(self) -> bool:
        """Return True if the following list is due for a re-sync."""
        if self.last_following_sync is None:
            return True
        return datetime.now() - self.last_following_sync >= timedelta(
            hours=FOLLOWING_SYNC_INTERVAL_HOURS
        )

    # -- Pipeline capacity check ----------------------------------------------

    def _pipeline_slots_remaining(self) -> int:
        """Return how many new tweets the watcher should fetch this poll.

        Logic: only fetch while (executed_actions_today + in_flight) < DAILY_ACTION_LIMIT.
        - executed_actions_today: read from the shared .x_daily_actions.json
        - in_flight: files currently in Needs_Action + Pending_Approval + Approved
          that are tweet actions (haven't been executed yet)

        This ensures the watcher stops fetching once the pipeline is full and
        resumes only when executed actions free up capacity.
        """
        # 1. Read executed actions today from shared orchestrator counter
        executed_today = 0
        if X_DAILY_ACTIONS_PATH.exists():
            try:
                data = json.loads(X_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
                window_start_str = data.get("window_start_time", "")
                executed_today = data.get("actions_today", 0)
                # If the 24h window has expired, treat count as 0
                if window_start_str:
                    window_start = datetime.fromisoformat(window_start_str)
                    if datetime.now() - window_start >= timedelta(hours=QUOTA_WINDOW_HOURS):
                        executed_today = 0
            except Exception:
                logger.debug("Could not read X actions counter; assuming 0 executed.")

        # 2. Count in-flight files across the pipeline
        needs_action_dir = Path(self.needs_action)
        pending_dir = VAULT_PATH / "Pending_Approval"
        approved_dir = VAULT_PATH / "Approved"

        in_flight = (
            len(list(needs_action_dir.glob("TWEET_*.md")))
            + len(list(pending_dir.glob("ACTION_TWEET_*.md")))
            + len(list(approved_dir.glob("ACTION_TWEET_*.md")))
        )

        slots = DAILY_ACTION_LIMIT - executed_today - in_flight
        slots = max(0, slots)

        logger.info(
            "X pipeline capacity: limit=%d, executed=%d, in_flight=%d → slots_available=%d",
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
                    self.processed_ids = {str(tid): "legacy" for tid in data}
                logger.info("Loaded %d processed tweet IDs.", len(self.processed_ids))
            except Exception:
                logger.exception("Failed to load processed IDs; starting fresh.")
                self.processed_ids = {}

    def _save_processed_ids(self):
        PROCESSED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"processed": self.processed_ids}
        PROCESSED_IDS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- Tweet fetching via browser -------------------------------------------

    def _fetch_mentions(self) -> list[dict]:
        """Scrape the @mentions notifications page for new mentions."""
        tweets = []
        try:
            url = build_mentions_url(OWN_USERNAME)
            logger.debug("Navigating to mentions: %s", url)
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            human_delay(3.0, 5.0)

            for tweet in parse_tweets_from_page(self._page):
                tid = tweet.get("id", "")
                if not tid or tid in self.processed_ids:
                    continue
                if tweet.get("author_username", "").lower() == OWN_USERNAME.lower():
                    continue
                tweets.append({
                    "id": tid,
                    "text": tweet.get("text", ""),
                    "author_username": tweet.get("author_username", "unknown"),
                    "author_name": tweet.get("author_name", "Unknown"),
                    "author_id": "",
                    "created_at": tweet.get("timestamp", ""),
                    "conversation_id": "",
                    "type": "mention",
                    "source": "mentions",
                    "referenced_tweets": [],
                })

            if tweets:
                logger.info("Scraped %d new mention(s).", len(tweets))

        except Exception:
            logger.exception("Error scraping mentions page")

        return tweets

    def _fetch_watchlist_tweets(self) -> list[dict]:
        """Visit each watchlist account's profile page and scrape their latest tweets."""
        if not self.watchlist:
            logger.info("Watchlist is empty — skipping profile scraping.")
            return []

        tweets = []
        logger.info("Scanning %d watchlist profile(s)...", len(self.watchlist))

        for entry in self.watchlist:
            username = entry.get("username", "").strip()
            if not username:
                continue

            try:
                url = build_profile_url(username)
                self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                human_delay(3.0, 5.0)

                raw = parse_tweets_from_page(self._page)
                new_for_user = 0
                skipped_processed = 0
                skipped_author = 0

                for tweet in raw:
                    tid = tweet.get("id", "")
                    if not tid:
                        continue
                    if tid in self.processed_ids:
                        skipped_processed += 1
                        continue
                    # Only collect tweets authored by this watchlist person
                    if tweet.get("author_username", "").lower() != username.lower():
                        skipped_author += 1
                        continue

                    tweets.append({
                        "id": tid,
                        "text": tweet.get("text", ""),
                        "author_username": tweet.get("author_username", username),
                        "author_name": tweet.get("author_name", username),
                        "author_id": "",
                        "created_at": tweet.get("timestamp", ""),
                        "conversation_id": "",
                        "type": "watchlist",
                        "source": "profile",
                        "watchlist_notes": entry.get("notes", ""),
                        "referenced_tweets": [],
                    })
                    new_for_user += 1

                logger.info(
                    "@%-20s  page_tweets=%-3d  new=%-3d  already_seen=%-3d  other_author=%-3d",
                    username, len(raw), new_for_user, skipped_processed, skipped_author,
                )

            except Exception:
                logger.exception("Error scraping profile for @%s", username)

            human_delay(2.0, 4.0)  # polite gap between profile visits

        logger.info(
            "Watchlist scan complete: %d new tweet(s) from %d account(s).",
            len(tweets), len(self.watchlist),
        )
        return tweets

    # -- BaseWatcher interface ------------------------------------------------

    def check_for_updates(self) -> list:
        """Scrape mentions + watchlist profiles, deduplicated, pipeline-capacity-capped."""
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

        # Re-sync following list every FOLLOWING_SYNC_INTERVAL_HOURS
        if self._should_sync_following():
            self._sync_watchlist_from_following()

        try:
            all_tweets = []

            mentions = self._fetch_mentions()
            all_tweets.extend(mentions)

            human_delay(2.0, 4.0)

            watchlist_tweets = self._fetch_watchlist_tweets()
            all_tweets.extend(watchlist_tweets)

            # Deduplicate by tweet ID (mentions take priority)
            seen: set[str] = set()
            unique: list[dict] = []
            for t in all_tweets:
                if t["id"] not in seen:
                    seen.add(t["id"])
                    unique.append(t)

            # Cap to available pipeline slots
            if len(unique) > slots:
                logger.info(
                    "Found %d tweets but only %d pipeline slot(s) available. Capping.",
                    len(unique), slots,
                )
                unique = unique[:slots]

            logger.info(
                "Poll cycle complete — %d new tweet(s) queued for pipeline.",
                len(unique),
            )

            if self._context:
                save_session(self._context, SESSION_PATH)

            self._consecutive_failures = 0
            return unique

        except Exception:
            logger.exception("Error during browser polling cycle")
            self._consecutive_failures += 1

            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Browser failed %d times consecutively — restarting.",
                    self._consecutive_failures,
                )
                self._restart_browser()

            return []

    def create_action_file(self, tweet: dict) -> Path:
        """Create a structured Markdown file in Needs_Action/ for a tweet."""
        tid = tweet["id"]
        tweet_type = tweet.get("type", "unknown")
        author = _sanitize_filename(tweet.get("author_username", "unknown"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"TWEET_{timestamp}_{tweet_type}_{author}.md"

        ref_section = "None"
        if tweet.get("referenced_tweets"):
            ref_section = "\n".join(
                f"- Type: {r['type']}, Tweet ID: {r['id']}"
                for r in tweet["referenced_tweets"]
            )

        notes_section = ""
        if tweet.get("watchlist_notes"):
            notes_section = f"\n## Watchlist Notes\n{tweet['watchlist_notes']}\n"

        content = f"""---
type: tweet
source: x_twitter
tweet_id: "{tid}"
author_username: "{tweet.get('author_username', 'unknown')}"
author_name: "{tweet.get('author_name', 'Unknown')}"
author_id: "{tweet.get('author_id', '')}"
tweet_type: "{tweet_type}"
detection_source: "{tweet.get('source', 'unknown')}"
conversation_id: "{tweet.get('conversation_id', '')}"
created_at: "{tweet.get('created_at', '')}"
received_at: "{datetime.now().isoformat()}"
status: pending
---

# Tweet: {tweet_type} from @{tweet.get('author_username', 'unknown')}

## Metadata
| Field           | Value |
|-----------------|-------|
| Author          | @{tweet.get('author_username', 'unknown')} ({tweet.get('author_name', 'Unknown')}) |
| Tweet ID        | {tid} |
| Type            | {tweet_type} |
| Source          | {tweet.get('source', 'unknown')} |
| Created         | {tweet.get('created_at', 'N/A')} |
| Conversation ID | {tweet.get('conversation_id', 'N/A')} |

## Tweet Content
{tweet.get('text', '[No content]')}

## Referenced Tweets
{ref_section}
{notes_section}
## Raw Reference
- Tweet ID: `{tid}`
- Author ID: `{tweet.get('author_id', '')}`
- Detection source: `{tweet.get('source', 'unknown')}`
"""

        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")

        self.processed_ids[tid] = tweet.get("source", "unknown")
        self._save_processed_ids()

        return filepath

    def run(self):
        """Override run() to ensure browser cleanup on exit."""
        try:
            super().run()
        finally:
            logger.info("Shutting down browser...")
            self._stop_browser()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("x_watcher.py starting — X/Twitter Sense Component (Playwright)")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Session: %s", SESSION_PATH)
    logger.info("Watchlist: %s", WATCHLIST_PATH)
    logger.info("Poll interval: %ds", CHECK_INTERVAL)
    logger.info(
        "Daily action limit: %d replies per %d hours (watcher fetches until pipeline full)",
        DAILY_ACTION_LIMIT, QUOTA_WINDOW_HOURS,
    )
    logger.info("=" * 60)

    watcher = XWatcher()
    watcher.run()


if __name__ == "__main__":
    main()
