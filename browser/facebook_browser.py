"""
facebook_browser.py - Shared Playwright browser utilities for Facebook automation.

Provides:
- Browser launch with anti-detection measures
- Session (cookies/localStorage) persistence via storage_state
- DM/Messenger inbox parsing
- Thread message parsing
- Post parsing from the Facebook feed/page
- Login state verification
- Cookie consent / overlay dismissal
- Human-like delay helpers

Used by both facebook_watcher.py (persistent browser) and
facebook_actions.py (short-lived per-batch browser).
"""

import logging
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page

logger = logging.getLogger("facebook_browser")

# ---------------------------------------------------------------------------
# Selectors — update here if Facebook changes its DOM
# ---------------------------------------------------------------------------

SELECTORS = {
    # Login state — present only when logged in
    "logged_in_indicator": '[aria-label="Facebook"][role="link"], a[href*="/home.php"], [data-pagelet="LeftRail"]',

    # Messenger inbox — any <a> linking to a thread (JS-discovered, not CSS-matched)
    "conversation_item": 'a[href*="/messages/t/"]',

    # Individual message text within an open thread
    "message_bubble": 'div[dir="auto"]',

    # Messenger message input box (contenteditable)
    # Facebook renders this as a contenteditable div; multiple fallback selectors
    "message_input": 'div[aria-label="Message"][contenteditable="true"]',
    "message_input_fallback": 'div[role="textbox"][contenteditable="true"]',

    # Send button inside Messenger thread
    "send_button": 'div[aria-label="Press Enter to send"]',

    # Facebook post composer — "What's on your mind?" area.
    # Facebook does NOT use aria-label or placeholder on the trigger button.
    # We match it with JS text search (see _do_facebook_post in actions).
    "post_composer_trigger": 'div[role="button"]:has-text("mind")',

    # Post modal textarea (contenteditable)
    "post_textarea": 'div[role="textbox"][contenteditable="true"][aria-label*="mind"], div[aria-label*="post"][contenteditable="true"]',

    # Post submit button
    "post_submit": 'div[aria-label="Post"][role="button"]',

    # Cookie consent
    "cookie_accept": 'button[data-cookiebanner="accept_button"], [data-testid="cookie-policy-manage-dialog-accept-button"]',

    # Generic dismiss/close buttons
    "modal_close": '[aria-label="Close"]',
    "notif_not_now": 'div[aria-label="Not Now"], button:has-text("Not Now")',
}

# Anti-detection Chromium args (same as other browsers in this project)
CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

MESSENGER_INBOX_URL = "https://www.facebook.com/messages/"
FACEBOOK_HOME_URL = "https://www.facebook.com/"


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
        "viewport": {"width": 1366, "height": 768},
        "user_agent": USER_AGENT,
    }

    if session_path and session_path.exists():
        context_kwargs["storage_state"] = str(session_path)
        logger.info("Restoring session from %s", session_path)

    context = browser.new_context(**context_kwargs)

    # Override navigator.webdriver to reduce bot detection
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )

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

def check_login_state(page: Page, timeout: int = 15_000) -> bool:
    """Navigate to Facebook home and verify the user is logged in.

    Returns True if logged in, False otherwise.
    """
    try:
        page.goto(FACEBOOK_HOME_URL, wait_until="domcontentloaded", timeout=30_000)
        human_delay(2.0, 3.5)
        dismiss_overlays(page)

        # If redirected to login page, session is expired
        if "login" in page.url or "checkpoint" in page.url:
            logger.warning("Facebook session expired — redirected to login/checkpoint.")
            return False

        # Look for a nav element that only appears when logged in
        page.wait_for_selector(SELECTORS["logged_in_indicator"], timeout=timeout)
        return True
    except Exception:
        logger.debug("Facebook login check failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Cookie / overlay dismissal
# ---------------------------------------------------------------------------

def dismiss_overlays(page: Page) -> None:
    """Dismiss cookie consent banners and any dialog that blocks interaction.

    Handles known Facebook dialogs including the "Post and reel default audience
    merge" popup that intercepts pointer events on the post composer.
    """
    # 1. Click known dismiss/close buttons
    for key in ("cookie_accept", "modal_close", "notif_not_now"):
        try:
            btn = page.locator(SELECTORS[key]).first
            if btn.is_visible(timeout=1_500):
                btn.click(timeout=3_000)
                human_delay(0.3, 0.6)
        except Exception:
            pass

    # 2. Handle the "Post and reel default audience merge" dialog specifically.
    #    This popup contains a distinctive image and blocks all composer clicks.
    #    Find its primary CTA button and click it to dismiss.
    try:
        clicked = page.evaluate("""
            () => {
                // Look for the merge dialogue by its distinctive image alt text
                const mergeImg = document.querySelector(
                    'img[alt*="merge"], img[alt*="audience merge"], img[alt*="reel default"]'
                );
                if (mergeImg) {
                    // Walk up to find the dialog container, then click any CTA button inside
                    let container = mergeImg.closest('[role="dialog"]') || mergeImg.parentElement;
                    for (let i = 0; i < 6 && container; i++) {
                        const btn = container.querySelector(
                            'div[role="button"], span[role="button"]'
                        );
                        if (btn) {
                            btn.click();
                            return true;
                        }
                        container = container.parentElement;
                    }
                }
                return false;
            }
        """)
        if clicked:
            logger.info("Dismissed 'Post and reel audience merge' dialog.")
            human_delay(0.5, 1.0)
    except Exception:
        pass

    # 3. Aggressively remove any fixed/absolute overlay div[role=dialog] that
    #    is intercepting pointer events (the Playwright error message tells us
    #    "subtree intercepts pointer events").
    try:
        page.evaluate("""
            () => {
                // Remove dialogs and fixed overlays that block the feed
                const candidates = document.querySelectorAll(
                    '[role="dialog"], [data-pagelet="GrowthEduTour"], ' +
                    '[data-pagelet="RightRailAds"], [aria-label="Cookie Policy"]'
                );
                for (const el of candidates) {
                    const style = window.getComputedStyle(el);
                    // Only remove if it is visually overlaying the page
                    if (style.position === 'fixed' || style.position === 'absolute') {
                        el.remove();
                    }
                }

                // Also remove any element whose subtree contains the merge dialogue image
                document.querySelectorAll('img[alt*="merge"], img[alt*="audience"]').forEach(img => {
                    const dialog = img.closest('[role="dialog"]');
                    if (dialog) dialog.remove();
                });
            }
        """)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Messenger inbox parsing
# ---------------------------------------------------------------------------

def parse_inbox_from_page(page: Page, max_conversations: int = 20) -> list[dict]:
    """Parse the Messenger inbox and return a list of recent conversations.

    Uses JavaScript evaluation to find all <a> tags linking to /messages/t/ threads.
    This is much more reliable than CSS selectors on Facebook's obfuscated class names.

    Each entry:
    {
        "thread_id":    str,   # numeric or alphanumeric thread ID from URL
        "thread_url":  str,   # full Messenger thread URL
        "sender_text": str,   # display name(s) shown for the conversation
        "preview_text": str,  # latest message preview text
    }
    """
    # Wait for at least one conversation link to appear
    try:
        page.wait_for_selector(SELECTORS["conversation_item"], timeout=15_000)
    except Exception:
        logger.debug("No conversation links found on Messenger inbox page.")
        return []

    raw = page.evaluate("""(maxConvs) => {
        const seen = new Set();
        const results = [];

        // All anchor tags linking to a Messenger thread
        const links = document.querySelectorAll('a[href*="/messages/t/"]');

        for (const link of links) {
            if (results.length >= maxConvs) break;

            const href = link.getAttribute('href') || '';

            // Extract thread_id from /messages/t/{id}/
            const match = href.match(/\\/messages\\/t\\/([^/?#]+)/);
            if (!match) continue;
            const threadId = match[1];
            if (seen.has(threadId)) continue;
            seen.add(threadId);

            // Grab all visible text inside the link
            const allText = link.innerText || '';
            const lines = allText.split('\\n').map(l => l.trim()).filter(Boolean);
            const senderText = lines[0] || 'Unknown';
            const previewText = lines.slice(1).join(' ');

            results.push({
                thread_id: threadId,
                thread_url: 'https://www.facebook.com/messages/t/' + threadId + '/',
                sender_text: senderText,
                preview_text: previewText,
            });
        }
        return results;
    }""", max_conversations)

    conversations = raw or []
    logger.debug("parse_inbox_from_page: found %d conversation(s)", len(conversations))
    return conversations


def _extract_thread_id(href: str) -> str:
    """Extract the thread ID from a Messenger URL."""
    # Handles both /messages/t/1234567890/ and /messages/t/username/
    try:
        parts = [p for p in href.split("/") if p]
        for i, part in enumerate(parts):
            if part == "t" and i + 1 < len(parts):
                return parts[i + 1].split("?")[0]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Thread message parsing
# ---------------------------------------------------------------------------

def parse_messages_from_page(page: Page) -> list[dict]:
    """Parse messages from an open Messenger conversation thread.

    Returns a list of message dicts, most-recent last:
    {
        "text": str,
        "is_incoming": bool,
    }
    """
    messages = []
    try:
        human_delay(1.5, 2.5)
        # Use JS to extract message bubbles with direction hints
        raw = page.evaluate("""() => {
            const results = [];
            // Message rows — each row contains one bubble
            const rows = document.querySelectorAll('div[role="row"]');
            for (const row of rows) {
                const textEls = row.querySelectorAll('div[dir="auto"]');
                const texts = [];
                for (const el of textEls) {
                    const t = el.innerText.trim();
                    if (t) texts.push(t);
                }
                const text = texts.join(' ').trim();
                if (!text) continue;

                // Outgoing messages are typically right-aligned / have a sent indicator
                const rowHtml = row.innerHTML;
                const isOutgoing = (
                    rowHtml.includes('justify-content: flex-end') ||
                    rowHtml.includes('self-end') ||
                    row.getAttribute('data-testid') === 'outgoing-message'
                );

                results.push({ text, is_incoming: !isOutgoing });
            }
            return results;
        }""")
        messages = raw or []
    except Exception:
        logger.exception("Error parsing Messenger thread messages")

    return messages


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def build_inbox_url() -> str:
    """Return the Messenger inbox URL."""
    return MESSENGER_INBOX_URL


def build_thread_url(thread_id: str) -> str:
    """Return the Messenger thread URL for a given thread_id."""
    return f"https://www.facebook.com/messages/t/{thread_id}/"


def build_home_url() -> str:
    """Return the Facebook home/feed URL."""
    return FACEBOOK_HOME_URL


# ---------------------------------------------------------------------------
# Human-like delays
# ---------------------------------------------------------------------------

def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Sleep for a random duration to mimic human behaviour."""
    time.sleep(random.uniform(min_sec, max_sec))
