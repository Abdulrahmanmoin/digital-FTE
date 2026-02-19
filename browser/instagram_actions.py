"""
instagram_actions.py - Instagram DM Reply Executor

Responsibility:
- Executes approved Instagram DM replies via Playwright browser automation
- Opens a short-lived browser per action batch, closes it after completion
- Called directly by orchestrator.py (not as a subprocess)

Boundary:
- Sends DM replies ONLY — does NOT like posts, follow users, or post content
- Only executes AFTER human approval (file moved to Approved/ folder)
- Does NOT read new messages — that is instagram_watcher.py's job

Assumptions:
- Session file exists at credentials/instagram_session.json
  (created by browser/instagram_setup.py)
"""

import logging
from pathlib import Path

from browser.instagram_browser import (
    SELECTORS,
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    dismiss_overlays,
    human_delay,
    build_thread_url,
)

logger = logging.getLogger("instagram_actions")

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_PATH = BASE_DIR / "credentials" / "instagram_session.json"


# ---------------------------------------------------------------------------
# Reply helper
# ---------------------------------------------------------------------------

def _find_message_input(page):
    """Try multiple selectors to locate the message composer."""
    for key in ("message_input", "message_input_fallback_1", "message_input_fallback_2"):
        try:
            el = page.locator(SELECTORS[key]).first
            if el.is_visible(timeout=3_000):
                return el
        except Exception:
            continue
    return None


def _send_reply(page, reply_text: str) -> bool:
    """Type and send a reply in the currently open conversation."""
    try:
        # Find the message input
        composer = _find_message_input(page)
        if composer is None:
            logger.error("Could not locate message input box.")
            return False

        composer.click(timeout=5_000)
        human_delay(0.5, 1.0)

        # Type with realistic keystroke delay (required for contenteditable)
        page.keyboard.type(reply_text, delay=40)
        human_delay(0.8, 1.5)

        # Try Enter key first (most reliable send method)
        page.keyboard.press("Enter")
        human_delay(1.5, 2.5)

        # Verify input cleared — sign that message was sent
        composer_after = _find_message_input(page)
        if composer_after:
            text_after = composer_after.inner_text().strip()
            if text_after == "" or text_after == reply_text:
                # Empty = sent. Still showing text = may have failed; try Send button
                if text_after == reply_text:
                    logger.warning("Input still populated after Enter — trying Send button.")
                    try:
                        send_btn = page.locator(SELECTORS["send_button"]).first
                        send_btn.click(timeout=5_000)
                        human_delay(1.5, 2.0)
                    except Exception:
                        logger.error("Send button not found either.")
                        return False

        logger.info("Reply sent successfully.")
        return True

    except Exception:
        logger.exception("Error sending reply")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_instagram_reply(
    thread_id: str,
    reply_text: str,
    sender_username: str = "",
    session_path: str | Path | None = None,
) -> bool:
    """
    Navigate to the given Instagram DM thread and send `reply_text`.

    Returns True on success, False on any failure.
    """
    _session = Path(session_path) if session_path else SESSION_PATH

    if not _session.exists():
        logger.error(
            "Instagram session file not found at %s. "
            "Run 'python browser/instagram_setup.py' to log in first.",
            _session,
        )
        return False

    if not reply_text.strip():
        logger.error("reply_text is empty — nothing to send.")
        return False

    pw = None
    browser = None
    try:
        pw = create_playwright_instance()
        browser, context = launch_browser(pw, headless=True, session_path=_session)
        page = context.new_page()

        # Verify session is still valid
        if not check_login_state(page):
            logger.error(
                "Instagram session expired. "
                "Run 'python browser/instagram_setup.py' to re-login."
            )
            return False

        human_delay(1.5, 2.5)

        # Navigate to the specific conversation thread
        thread_url = build_thread_url(thread_id)
        logger.info(
            "Opening conversation thread %s (@%s) ...",
            thread_id, sender_username or "unknown",
        )
        page.goto(thread_url, wait_until="domcontentloaded", timeout=30_000)
        human_delay(2.5, 4.0)
        dismiss_overlays(page)

        # Wait for message input to be ready
        try:
            page.wait_for_selector(
                f'{SELECTORS["message_input"]}, '
                f'{SELECTORS["message_input_fallback_1"]}, '
                f'{SELECTORS["message_input_fallback_2"]}',
                timeout=15_000,
            )
        except Exception:
            logger.warning("Message input did not appear within 15s — attempting anyway.")

        human_delay(1.0, 2.0)

        success = _send_reply(page, reply_text)

        # Save fresh session cookies
        save_session(context, _session)

        return success

    except Exception:
        logger.exception(
            "Unexpected error executing Instagram reply for thread %s", thread_id
        )
        return False

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
