"""
instagram_browser.py - Shared Playwright Utilities for Instagram

Provides:
- Browser launch with anti-detection args and session restore
- Login state verification
- Inbox parsing (conversation list)
- Thread message parsing
- Session save/restore
- Human-like delay helper

NOTE: Instagram frequently changes its DOM. If selectors break, update the
SELECTORS dict below — all selector strings are defined in one place.
"""

import random
import time
import logging
from pathlib import Path

from playwright.sync_api import Playwright, Browser, BrowserContext, Page, sync_playwright

logger = logging.getLogger("instagram_browser")

# ---------------------------------------------------------------------------
# Selectors — update here if Instagram changes its DOM
# ---------------------------------------------------------------------------

SELECTORS = {
    # Login state — if this is absent after loading inbox we are not logged in
    "logged_in_indicator": 'svg[aria-label="Direct"]',

    # Inbox conversation items — each conversation is a link to a thread
    "conversation_link": 'a[href*="/direct/t/"]',

    # Within a conversation link: sender name and message preview text
    "conversation_text": 'div[dir="auto"]',

    # Within a thread: incoming message bubbles (text content)
    "message_row":  'div[role="row"]',
    "message_text": 'div[dir="auto"]',

    # Message composer input
    "message_input": 'div[aria-label="Message..."][contenteditable="true"]',
    # Fallbacks if primary input selector fails
    "message_input_fallback_1": 'div[role="textbox"][contenteditable="true"]',
    "message_input_fallback_2": 'div[contenteditable="true"]',

    # Send button (Enter key is tried first; this is the fallback)
    "send_button": 'button[aria-label="Send"]',

    # Overlay / modal dismissals
    "notif_not_now":   'button:has-text("Not Now")',
    "dialog_dismiss":  'button[aria-label="Close"]',
    "cookie_accept":   'button:has-text("Allow all cookies")',
    "cookie_decline":  'button:has-text("Decline optional cookies")',
}

# ---------------------------------------------------------------------------
# Browser launch configuration
# ---------------------------------------------------------------------------

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

INBOX_URL = "https://www.instagram.com/direct/inbox/"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Sleep a random duration to mimic human behaviour."""
    time.sleep(random.uniform(min_sec, max_sec))


def create_playwright_instance() -> Playwright:
    return sync_playwright().start()


def launch_browser(
    pw: Playwright,
    headless: bool = True,
    session_path: str | Path | None = None,
) -> tuple[Browser, BrowserContext]:
    browser = pw.chromium.launch(headless=headless, args=CHROMIUM_ARGS)

    context_kwargs = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": USER_AGENT,
    }
    if session_path and Path(session_path).exists():
        context_kwargs["storage_state"] = str(session_path)

    context = browser.new_context(**context_kwargs)

    # Mask automation fingerprint
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )

    return browser, context


def save_session(context: BrowserContext, session_path: str | Path):
    """Persist cookies and localStorage to disk."""
    Path(session_path).parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(session_path))


def build_inbox_url() -> str:
    return INBOX_URL


def build_thread_url(thread_id: str) -> str:
    return f"https://www.instagram.com/direct/t/{thread_id}/"


# ---------------------------------------------------------------------------
# Overlay / modal dismissal
# ---------------------------------------------------------------------------

def dismiss_overlays(page: Page):
    """Dismiss any modal dialogs Instagram shows (notifications, cookies, etc.)."""
    for key in ("notif_not_now", "dialog_dismiss", "cookie_decline", "cookie_accept"):
        try:
            btn = page.locator(SELECTORS[key]).first
            if btn.is_visible(timeout=1_500):
                btn.click(timeout=3_000)
                human_delay(0.5, 1.0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Login state check
# ---------------------------------------------------------------------------

def check_login_state(page: Page, timeout: int = 10_000) -> bool:
    """
    Navigate to the DM inbox and verify the session is still valid.
    Returns True if logged in, False if redirected to the login page.
    """
    try:
        page.goto(INBOX_URL, wait_until="domcontentloaded", timeout=30_000)
        human_delay(2.0, 3.0)
        dismiss_overlays(page)

        # If we got redirected to login, URL will contain 'accounts/login'
        if "accounts/login" in page.url or "challenge" in page.url:
            logger.warning("Instagram session expired — redirected to login page.")
            return False

        # Wait for the Direct icon which only appears when logged in
        page.wait_for_selector(SELECTORS["logged_in_indicator"], timeout=timeout)
        return True
    except Exception:
        logger.debug("Login check failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Inbox parsing
# ---------------------------------------------------------------------------

def parse_inbox_from_page(page: Page, max_conversations: int = 20) -> list[dict]:
    """
    Parse the DM inbox and return a list of conversations.

    Each entry:
    {
        "thread_id": str,          # numeric thread ID from URL
        "thread_url": str,         # full URL
        "preview_text": str,       # message preview shown in inbox
        "sender_text": str,        # display name(s) shown in inbox item
    }
    """
    conversations = []
    try:
        links = page.locator(SELECTORS["conversation_link"]).all()
        seen_ids = set()

        for link in links[:max_conversations]:
            try:
                href = link.get_attribute("href") or ""
                # Extract thread_id from /direct/t/{thread_id}/
                parts = [p for p in href.split("/") if p]
                thread_id = ""
                for i, part in enumerate(parts):
                    if part == "t" and i + 1 < len(parts):
                        thread_id = parts[i + 1]
                        break

                if not thread_id or thread_id in seen_ids:
                    continue
                seen_ids.add(thread_id)

                # Extract text content for sender name + preview
                all_text = link.inner_text().strip()
                lines = [l.strip() for l in all_text.splitlines() if l.strip()]
                sender_text = lines[0] if lines else "Unknown"
                preview_text = " ".join(lines[1:]) if len(lines) > 1 else ""

                conversations.append({
                    "thread_id": thread_id,
                    "thread_url": build_thread_url(thread_id),
                    "sender_text": sender_text,
                    "preview_text": preview_text,
                })
            except Exception:
                logger.debug("Error parsing one conversation link", exc_info=True)

    except Exception:
        logger.exception("Error parsing inbox")

    return conversations


# ---------------------------------------------------------------------------
# Thread message parsing
# ---------------------------------------------------------------------------

def parse_messages_from_page(page: Page, own_username: str = "") -> list[dict]:
    """
    Parse messages from an open conversation thread.

    Returns a list of message dicts, most-recent last:
    {
        "text": str,
        "is_incoming": bool,   # True = sent by the other person
    }
    """
    messages = []
    try:
        human_delay(1.5, 2.5)
        rows = page.locator(SELECTORS["message_row"]).all()

        for row in rows:
            try:
                text_els = row.locator(SELECTORS["message_text"]).all()
                text = " ".join(
                    el.inner_text().strip()
                    for el in text_els
                    if el.inner_text().strip()
                )
                if not text:
                    continue

                # Instagram outgoing messages are usually right-aligned
                # Check for aria attributes or alignment hints
                # This is a best-effort heuristic — may need tuning
                row_html = row.inner_html()
                is_outgoing = (
                    'justify-content: flex-end' in row_html
                    or 'align-self: flex-end' in row_html
                    or 'dir="ltr"' in row_html  # outgoing messages in some versions
                )
                is_incoming = not is_outgoing

                messages.append({"text": text, "is_incoming": is_incoming})
            except Exception:
                continue

    except Exception:
        logger.exception("Error parsing thread messages")

    return messages
