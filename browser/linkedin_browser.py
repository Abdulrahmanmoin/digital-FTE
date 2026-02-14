"""
linkedin_browser.py - Shared Playwright browser utilities for LinkedIn automation.

Provides:
- Browser launch with anti-detection measures
- Session (cookies/localStorage) persistence via storage_state
- Post parsing from LinkedIn feed DOM
- Login state verification
- Cookie consent dismissal
- Human-like delay helpers

Used by both linkedin_watcher.py (persistent browser) and linkedin_actions.py (short-lived).
"""

import logging
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page

logger = logging.getLogger("linkedin_browser")

# ---------------------------------------------------------------------------
# Selectors — centralised for easy maintenance
# ---------------------------------------------------------------------------

SELECTORS = {
    # Login state indicator
    "nav_me": ".global-nav__me",

    # Feed posts
    "post_container": "div[data-id*='urn:li:activity']",

    # Like button states.
    # IMPORTANT: Use exact aria-label matches, not substrings.
    # "Unreact Like" contains "React Like" as a substring — a *=' match would
    # accidentally find the already-liked button when looking for the like button.
    "like_button": 'button[aria-label="React Like"]',
    "liked_button": 'button[aria-label="Unreact Like"]',

    # Comment action button (on post page social bar)
    "comment_button": 'button[aria-label="Comment"]',

    # Comment editor — Quill contenteditable div (confirmed from live DOM)
    "comment_editor": 'div.ql-editor[aria-label="Text editor for creating content"]',

    # Comment submit button — appears (and becomes enabled) after text is typed
    "comment_submit": "button.comments-comment-box__submit-button--cr",

    # Start a post — button has NO aria-label; matched by visible text via Playwright
    # Use page.locator('button:has-text("Start a post")') in action code
    "start_post_trigger": 'button:has-text("Start a post")',

    # Post compose modal editor (same Quill editor aria-label as comment editor)
    "post_textarea": 'div.ql-editor[aria-label="Text editor for creating content"]',

    # Post submit — disabled until text is entered; wait for :not([disabled])
    "post_submit": "button.share-actions__primary-action",

    # Cookie consent
    "cookie_accept": "button[action-type='ACCEPT']",

    # Generic dismiss
    "modal_dismiss": "button[aria-label='Dismiss']",
}

# Anti-detection Chromium args (same as x_browser)
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
    """Check if the user is logged in by looking for the global nav 'Me' element."""
    try:
        page.goto(build_feed_url(), wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector(SELECTORS["nav_me"], timeout=timeout)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cookie / overlay dismissal
# ---------------------------------------------------------------------------

def dismiss_cookie_consent(page: Page) -> None:
    """Accept LinkedIn's cookie consent banner if it is present."""
    try:
        btn = page.query_selector(SELECTORS["cookie_accept"])
        if btn and btn.is_visible():
            btn.click()
            human_delay(0.5, 1.0)
            logger.debug("Cookie consent dismissed.")
    except Exception:
        logger.debug("No cookie consent banner found (or failed to dismiss).")


# ---------------------------------------------------------------------------
# Post parsing
# ---------------------------------------------------------------------------

def parse_posts_from_page(page: Page, max_posts: int = 15) -> list[dict]:
    """Scroll the LinkedIn feed and extract posts from activity URN containers.

    Returns a list of dicts with keys:
        id, urn, text, author_name, author_username, timestamp
    """
    # Wait for at least one post container
    try:
        page.wait_for_selector(SELECTORS["post_container"], timeout=20_000)
    except Exception:
        logger.debug("No post containers found on page %s", page.url)
        return []

    # Scroll to load more posts
    for _ in range(3):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        human_delay(1.5, 2.5)

    posts = page.evaluate("""(maxPosts) => {
        const containers = document.querySelectorAll("div[data-id*='urn:li:activity']");
        const results = [];

        for (const container of Array.from(containers).slice(0, maxPosts)) {
            try {
                const urn = container.getAttribute('data-id') || '';
                // Extract activity ID from urn:li:activity:1234567890
                const urnMatch = urn.match(/urn:li:activity:(\\d+)/);
                const postId = urnMatch ? urnMatch[1] : '';

                if (!postId) continue;

                // Extract post text — look for the main update text container
                let text = '';
                const textEl = container.querySelector(
                    '.feed-shared-update-v2__description .break-words, ' +
                    '.update-components-text, ' +
                    '.feed-shared-text'
                );
                if (textEl) text = textEl.innerText.trim();

                // Extract author name and link-based username
                let authorName = '';
                let authorUsername = '';
                const actorEl = container.querySelector(
                    '.update-components-actor__name span[aria-hidden="true"], ' +
                    '.feed-shared-actor__name'
                );
                if (actorEl) authorName = actorEl.innerText.trim();

                // LinkedIn doesn't expose /in/username on all feed cards,
                // but we can extract it from the profile link if present.
                const profileLink = container.querySelector(
                    'a.update-components-actor__meta-link, ' +
                    'a.feed-shared-actor__container-link'
                );
                if (profileLink) {
                    const href = profileLink.getAttribute('href') || '';
                    const slugMatch = href.match(/\\/in\\/([^/?]+)/);
                    if (slugMatch) authorUsername = slugMatch[1];
                }

                // Timestamp — look for time element or aria-label
                let timestamp = '';
                const timeEl = container.querySelector('time, .feed-shared-actor__sub-description');
                if (timeEl) {
                    timestamp = timeEl.getAttribute('datetime') ||
                                timeEl.innerText.trim() || '';
                }

                results.push({
                    id: postId,
                    urn: urn,
                    text: text,
                    author_name: authorName,
                    author_username: authorUsername,
                    timestamp: timestamp,
                });
            } catch (e) {
                // Skip malformed post containers
            }
        }
        return results;
    }""", max_posts)

    return posts or []


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def build_feed_url() -> str:
    """Return the LinkedIn main feed URL."""
    return "https://www.linkedin.com/feed/"


def build_post_url(urn: str) -> str:
    """Return the permalink for a LinkedIn activity post."""
    return f"https://www.linkedin.com/feed/update/{urn}/"


# ---------------------------------------------------------------------------
# Human-like delays
# ---------------------------------------------------------------------------

def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Sleep for a random duration to mimic human behaviour."""
    time.sleep(random.uniform(min_sec, max_sec))
