"""
x_watcher.py - X/Twitter Sense Component (Playwright Browser Automation)

Responsibility:
- Connects to X/Twitter via headless Chromium browser (Playwright)
- Polls for new mentions and keyword matches by scraping pages
- Creates a structured Markdown file in AI_Employee_Vault/Needs_Action/ for each
  detected tweet containing metadata, content, and engagement context
- Tracks already-processed tweet IDs to avoid duplicates (persisted to disk)
- Keeps browser open between poll cycles; saves session state after each poll

Boundary:
- READ-ONLY scraping — does NOT like, retweet, reply, or post
- Does NOT reason, plan, approve, or execute actions
- Does NOT trigger the orchestrator directly; communication is file-based only

Assumptions:
- Session file at credentials/x_session.json (created via browser/x_setup.py)
- Keywords config at credentials/x_keywords.json
- The vault path is resolved relative to this script's parent directory
"""

import json
import logging
import re
import sys
from datetime import datetime
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
    build_search_url,
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
KEYWORDS_PATH = CREDENTIALS_DIR / "x_keywords.json"
PROCESSED_IDS_PATH = CREDENTIALS_DIR / ".x_processed_ids.json"

CHECK_INTERVAL = 180  # seconds between polls (3 minutes)

# Our own X/Twitter username (without @)
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
        self.processed_ids: dict[str, str] = {}  # tweet_id -> source (mention/search)
        self.keywords: list[str] = []

        # Browser state
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._browser_healthy = False
        self._consecutive_failures = 0

        self._load_processed_ids()
        self._load_keywords()
        self._start_browser()

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

            # Verify login
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

    def _load_keywords(self):
        """Load keyword search terms from config file."""
        if KEYWORDS_PATH.exists():
            try:
                self.keywords = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
                logger.info("Loaded %d keywords from %s", len(self.keywords), KEYWORDS_PATH)
            except Exception:
                logger.exception("Failed to load keywords; using empty list.")
                self.keywords = []
        else:
            logger.warning("Keywords file not found at %s. No keyword search.", KEYWORDS_PATH)
            self.keywords = []

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
        """Scrape the mentions/notifications page for new mentions."""
        tweets = []
        try:
            mentions_url = build_mentions_url(OWN_USERNAME)
            logger.debug("Navigating to %s", mentions_url)
            self._page.goto(mentions_url, wait_until="domcontentloaded", timeout=30_000)
            human_delay(3.0, 5.0)

            raw_tweets = parse_tweets_from_page(self._page)

            for tweet in raw_tweets:
                tid = tweet.get("id", "")
                if not tid or tid in self.processed_ids:
                    continue

                # Skip our own tweets
                if tweet.get("author_username", "").lower() == OWN_USERNAME.lower():
                    continue

                tweets.append({
                    "id": tid,
                    "text": tweet.get("text", ""),
                    "author_username": tweet.get("author_username", "unknown"),
                    "author_name": tweet.get("author_name", "Unknown"),
                    "author_id": "",  # Not available via scraping
                    "created_at": tweet.get("timestamp", ""),
                    "conversation_id": "",  # Not available via scraping
                    "type": "mention",
                    "source": "mentions",
                    "referenced_tweets": [],
                })

            if tweets:
                logger.info("Scraped %d new mention(s).", len(tweets))

        except Exception:
            logger.exception("Error scraping mentions page")

        return tweets

    def _fetch_keyword_results(self) -> list[dict]:
        """Scrape search results pages for each configured keyword."""
        if not self.keywords:
            return []

        tweets = []
        for keyword in self.keywords:
            try:
                search_url = build_search_url(keyword)
                logger.debug("Searching for '%s': %s", keyword, search_url)
                self._page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                human_delay(3.0, 5.0)

                raw_tweets = parse_tweets_from_page(self._page)

                for tweet in raw_tweets:
                    tid = tweet.get("id", "")
                    if not tid or tid in self.processed_ids:
                        continue

                    # Skip our own tweets
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
                        "type": "keyword_match",
                        "source": "search",
                        "matched_keyword": keyword,
                        "referenced_tweets": [],
                    })

            except Exception:
                logger.exception("Error searching for keyword '%s'", keyword)

        if tweets:
            logger.info("Scraped %d new keyword match(es).", len(tweets))
        return tweets

    # -- BaseWatcher interface ------------------------------------------------

    def check_for_updates(self) -> list:
        """Scrape mentions and keyword search pages, deduplicated."""
        if not self._browser_healthy:
            # Try to recover if session file exists
            if SESSION_PATH.exists():
                logger.warning("Browser unhealthy — attempting restart.")
                self._restart_browser()
            else:
                logger.warning("Browser unhealthy and no session file. Skipping poll.")
            if not self._browser_healthy:
                return []

        try:
            all_tweets = []

            mentions = self._fetch_mentions()
            all_tweets.extend(mentions)

            human_delay(2.0, 4.0)

            keyword_hits = self._fetch_keyword_results()
            all_tweets.extend(keyword_hits)

            # Deduplicate by tweet ID (mentions take priority over search)
            seen = set()
            unique = []
            for t in all_tweets:
                if t["id"] not in seen:
                    seen.add(t["id"])
                    unique.append(t)

            if unique:
                logger.info("Total new tweets to process: %d", len(unique))

            # Save session state to keep cookies fresh
            if self._context:
                save_session(self._context, SESSION_PATH)

            # Reset failure counter on success
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

        # Build referenced tweets section
        ref_section = ""
        if tweet.get("referenced_tweets"):
            ref_lines = []
            for ref in tweet["referenced_tweets"]:
                ref_lines.append(f"- Type: {ref['type']}, Tweet ID: {ref['id']}")
            ref_section = "\n".join(ref_lines)
        else:
            ref_section = "None"

        # Build keyword match section
        keyword_section = ""
        if tweet.get("matched_keyword"):
            keyword_section = f"\n## Matched Keyword\n{tweet['matched_keyword']}\n"

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
| Field      | Value |
|------------|-------|
| Author     | @{tweet.get('author_username', 'unknown')} ({tweet.get('author_name', 'Unknown')}) |
| Tweet ID   | {tid} |
| Type       | {tweet_type} |
| Source     | {tweet.get('source', 'unknown')} |
| Created    | {tweet.get('created_at', 'N/A')} |
| Conversation ID | {tweet.get('conversation_id', 'N/A')} |

## Tweet Content
{tweet.get('text', '[No content]')}

## Referenced Tweets
{ref_section}
{keyword_section}
## Raw Reference
- Tweet ID: `{tid}`
- Author ID: `{tweet.get('author_id', '')}`
- Detection source: `{tweet.get('source', 'unknown')}`
"""

        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")

        # Track as processed and persist
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
    logger.info("Keywords: %s", KEYWORDS_PATH)
    logger.info("Poll interval: %ds", CHECK_INTERVAL)
    logger.info("=" * 60)

    watcher = XWatcher()
    watcher.run()


if __name__ == "__main__":
    main()
