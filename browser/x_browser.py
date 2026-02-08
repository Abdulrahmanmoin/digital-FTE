"""
x_browser.py - Shared Playwright browser utilities for X/Twitter automation.

Provides:
- Browser launch with anti-detection measures
- Session (cookies/localStorage) persistence via storage_state
- Tweet parsing from page DOM
- Login state verification
- Search URL building
- Human-like delay helpers

Used by both x_watcher.py (persistent browser) and x_actions.py (short-lived browser).
"""

import json
import logging
import random
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page

logger = logging.getLogger("x_browser")

# ---------------------------------------------------------------------------
# Selectors — centralised for easy maintenance
# ---------------------------------------------------------------------------

SELECTORS = {
    # Tweet elements
    "tweet_article": 'article[data-testid="tweet"]',
    "tweet_text": 'div[data-testid="tweetText"]',
    "tweet_user_name": 'div[data-testid="User-Name"]',
    "tweet_time": "time",

    # Action buttons (on a tweet detail page)
    "like_button": 'button[data-testid="like"]',
    "unlike_button": 'button[data-testid="unlike"]',
    "retweet_button": 'button[data-testid="retweet"]',
    "unretweet_button": 'button[data-testid="unretweet"]',
    "retweet_confirm": '[data-testid="retweetConfirm"]',
    "reply_button": 'button[data-testid="reply"]',

    # Compose / reply
    "tweet_textarea": 'div[data-testid="tweetTextarea_0"]',
    "tweet_submit": 'button[data-testid="tweetButton"]',

    # Login state indicator
    "compose_button": 'a[data-testid="SideNav_NewTweet_Button"]',
}

# Anti-detection Chromium args
CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]


# ---------------------------------------------------------------------------
# Browser lifecycle
# ---------------------------------------------------------------------------

def create_playwright_instance() -> Playwright:
    """Start and return a Playwright instance (sync API)."""
    return sync_playwright().start()


def launch_browser(
    pw: Playwright,
    headless: bool = True,
    session_path: str | Path | None = None,
) -> tuple[Browser, BrowserContext]:
    """Launch Chromium with anti-detection args and optional session restore.

    Returns (Browser, BrowserContext).
    """
    session_path = Path(session_path) if session_path else None

    browser = pw.chromium.launch(
        headless=headless,
        args=CHROMIUM_ARGS,
    )

    context_kwargs: dict = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }

    if session_path and session_path.exists():
        context_kwargs["storage_state"] = str(session_path)
        logger.info("Restoring session from %s", session_path)

    context = browser.new_context(**context_kwargs)

    # Override navigator.webdriver to avoid detection
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    return browser, context


def save_session(context: BrowserContext, session_path: str | Path):
    """Persist cookies and localStorage to a JSON file."""
    session_path = Path(session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(session_path))
    logger.debug("Session saved to %s", session_path)


# ---------------------------------------------------------------------------
# Login verification
# ---------------------------------------------------------------------------

def check_login_state(page: Page, timeout: int = 10_000) -> bool:
    """Check if the user is logged in by looking for the compose tweet button."""
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector(SELECTORS["compose_button"], timeout=timeout)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tweet parsing
# ---------------------------------------------------------------------------

def parse_tweets_from_page(page: Page) -> list[dict]:
    """Extract tweets from the current page using JS evaluation.

    Returns a list of dicts with keys: id, text, author_username,
    author_name, timestamp, tweet_url.
    """
    # Wait for tweet articles to appear
    try:
        page.wait_for_selector(SELECTORS["tweet_article"], timeout=15_000)
    except Exception:
        logger.debug("No tweet articles found on page %s", page.url)
        return []

    tweets = page.evaluate("""() => {
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        const results = [];

        for (const article of articles) {
            try {
                // Extract tweet text
                const textEl = article.querySelector('div[data-testid="tweetText"]');
                const text = textEl ? textEl.innerText : '';

                // Extract author info from User-Name section
                const userNameDiv = article.querySelector('div[data-testid="User-Name"]');
                let authorUsername = '';
                let authorName = '';
                if (userNameDiv) {
                    const links = userNameDiv.querySelectorAll('a[role="link"]');
                    for (const link of links) {
                        const href = link.getAttribute('href') || '';
                        if (href.startsWith('/') && !href.includes('/status/')) {
                            authorUsername = href.replace('/', '');
                            break;
                        }
                    }
                    // Display name is usually the first span with text
                    const nameSpans = userNameDiv.querySelectorAll('span');
                    for (const span of nameSpans) {
                        const t = span.innerText.trim();
                        if (t && !t.startsWith('@') && t !== '·') {
                            authorName = t;
                            break;
                        }
                    }
                }

                // Extract timestamp and tweet URL from the time element's parent link
                const timeEl = article.querySelector('time');
                let timestamp = '';
                let tweetUrl = '';
                let tweetId = '';
                if (timeEl) {
                    timestamp = timeEl.getAttribute('datetime') || '';
                    const timeLink = timeEl.closest('a');
                    if (timeLink) {
                        tweetUrl = timeLink.getAttribute('href') || '';
                        // Extract tweet ID from URL like /user/status/123456
                        const match = tweetUrl.match(/\\/status\\/(\\d+)/);
                        if (match) tweetId = match[1];
                    }
                }

                if (tweetId) {
                    results.push({
                        id: tweetId,
                        text: text,
                        author_username: authorUsername,
                        author_name: authorName,
                        timestamp: timestamp,
                        tweet_url: tweetUrl,
                    });
                }
            } catch (e) {
                // Skip malformed tweet articles
            }
        }
        return results;
    }""")

    return tweets or []


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def build_search_url(keyword: str) -> str:
    """Build an X search URL for a keyword (Latest tab, excluding retweets)."""
    query = f"{keyword} -filter:retweets"
    encoded = urllib.parse.quote(query)
    return f"https://x.com/search?q={encoded}&src=typed_query&f=live"


def build_mentions_url(username: str) -> str:
    """Build the notifications/mentions page URL."""
    return "https://x.com/notifications/mentions"


# ---------------------------------------------------------------------------
# Human-like delays
# ---------------------------------------------------------------------------

def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Sleep for a random duration to mimic human behavior."""
    time.sleep(random.uniform(min_sec, max_sec))
