"""
facebook_actions.py - Facebook action executor (Messenger replies + wall posts).

Responsibility:
- Executes approved Facebook actions via Playwright browser automation
- Supported actions:
    * Reply to a Messenger DM thread
    * Create an original Facebook wall post (text-only)
- Opens a short-lived browser per action batch, closes after completion
- Called directly by orchestrator.py (not as a subprocess)

Boundary:
- Sends DM replies and creates posts ONLY
- Only executes AFTER human approval (file moved to Approved/)
- Does NOT read new messages — that is facebook_watcher.py's job

Assumptions:
- Session file exists at credentials/facebook_session.json
  (created by browser/facebook_setup.py)
"""

import logging
from pathlib import Path

from browser.facebook_browser import (
    SELECTORS,
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    dismiss_overlays,
    build_thread_url,
    build_home_url,
    human_delay,
)

logger = logging.getLogger("facebook_actions")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SESSION_PATH = BASE_DIR / "credentials" / "facebook_session.json"


# ---------------------------------------------------------------------------
# Messenger reply
# ---------------------------------------------------------------------------

def _find_message_input(page):
    """Try multiple selectors to locate the Messenger message composer."""
    for key in ("message_input", "message_input_fallback"):
        try:
            el = page.locator(SELECTORS[key]).first
            if el.is_visible(timeout=3_000):
                return el
        except Exception:
            continue
    return None


def _send_messenger_reply(page, reply_text: str) -> bool:
    """Type and send a reply in the currently open Messenger conversation."""
    try:
        composer = _find_message_input(page)
        if composer is None:
            logger.error("Could not locate Messenger message input box.")
            return False

        composer.click(timeout=5_000)
        human_delay(0.5, 1.0)

        # Type with realistic keystroke delay (required for contenteditable)
        page.keyboard.type(reply_text, delay=40)
        human_delay(0.8, 1.5)

        # Press Enter to send (most reliable in Messenger)
        page.keyboard.press("Enter")
        human_delay(1.5, 2.5)

        # Verify: if input cleared, message was sent
        composer_after = _find_message_input(page)
        if composer_after:
            text_after = composer_after.inner_text().strip()
            if text_after == reply_text:
                # Still showing — try clicking the send button
                logger.warning("Input still populated after Enter — trying Send button.")
                try:
                    send_btn = page.locator(SELECTORS["send_button"]).first
                    send_btn.click(timeout=5_000)
                    human_delay(1.5, 2.0)
                except Exception:
                    logger.error("Send button not found either.")
                    return False

        logger.info("Messenger reply sent successfully.")
        return True

    except Exception:
        logger.exception("Error sending Messenger reply")
        return False


def execute_facebook_reply(
    thread_id: str,
    reply_text: str,
    sender_name: str = "",
    session_path: str | Path | None = None,
) -> bool:
    """Navigate to the given Messenger thread and send reply_text.

    Returns True on success, False on any failure.
    """
    _session = Path(session_path) if session_path else DEFAULT_SESSION_PATH

    if not _session.exists():
        logger.error(
            "Facebook session file not found at %s. "
            "Run 'python browser/facebook_setup.py' to log in first.",
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

        if not check_login_state(page):
            logger.error(
                "Facebook session expired. "
                "Run 'python browser/facebook_setup.py' to re-login."
            )
            return False

        human_delay(1.5, 2.5)

        thread_url = build_thread_url(thread_id)
        logger.info(
            "Opening Messenger thread %s (%s) ...",
            thread_id, sender_name or "unknown",
        )
        page.goto(thread_url, wait_until="domcontentloaded", timeout=30_000)
        human_delay(2.5, 4.0)
        dismiss_overlays(page)

        # Wait for message input
        try:
            page.wait_for_selector(
                f'{SELECTORS["message_input"]}, {SELECTORS["message_input_fallback"]}',
                timeout=15_000,
            )
        except Exception:
            logger.warning("Message input did not appear within 15s — attempting anyway.")

        human_delay(1.0, 2.0)

        success = _send_messenger_reply(page, reply_text)
        save_session(context, _session)
        return success

    except Exception:
        logger.exception(
            "Unexpected error executing Facebook reply for thread %s", thread_id
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


# ---------------------------------------------------------------------------
# Facebook wall post
# ---------------------------------------------------------------------------

def _click_post_composer(page) -> bool:
    """Find and click the 'What's on your mind?' post composer trigger.

    Facebook does not use consistent aria-labels or placeholders on this element.
    We use JavaScript text-content search as the most reliable approach.
    Returns True if the click succeeded.
    """
    # Strategy 1: Playwright :has-text() locator (handles partial text match)
    for text_fragment in ("mind", "post", "share"):
        try:
            locator = page.locator(f'div[role="button"]:has-text("{text_fragment}")').first
            if locator.is_visible(timeout=3_000):
                locator.click(timeout=5_000)
                logger.debug("Clicked post composer via :has-text('%s')", text_fragment)
                return True
        except Exception:
            pass

    # Strategy 2: JavaScript — walk every div[role=button] and look for text keywords
    try:
        clicked = page.evaluate("""
            () => {
                const keywords = ["mind", "post something", "share", "what's on"];
                const buttons = document.querySelectorAll('div[role="button"], span[role="button"]');
                for (const btn of buttons) {
                    const t = (btn.innerText || btn.textContent || '').toLowerCase();
                    if (keywords.some(k => t.includes(k))) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if clicked:
            logger.debug("Clicked post composer via JS text search.")
            return True
    except Exception:
        pass

    # Strategy 3: Click the feed's top contenteditable / input-like area
    try:
        el = page.locator('[aria-label*="post"], [aria-label*="share"], [aria-label*="mind"]').first
        if el.is_visible(timeout=3_000):
            el.click(timeout=5_000)
            logger.debug("Clicked post composer via aria-label fallback.")
            return True
    except Exception:
        pass

    logger.warning("Could not locate the post composer trigger.")
    return False


def _do_facebook_post(page, content: str) -> bool:
    """Create a new original Facebook post from the home feed.

    Relies on the page already being on the home feed (guaranteed by caller).
    """
    try:
        # Give the feed time to fully render, then dismiss any blocking dialogs.
        # The "Post and reel audience merge" popup often appears 2-3s after page load
        # and intercepts pointer events on the composer — must be dismissed first.
        human_delay(2.0, 3.5)
        dismiss_overlays(page)
        human_delay(0.5, 1.0)
        dismiss_overlays(page)  # second pass in case dialog appeared after first pass

        if not _click_post_composer(page):
            return False

        human_delay(1.5, 2.5)
        dismiss_overlays(page)

        # Find the post textarea inside the compose modal.
        # Try progressively broader selectors — Facebook uses obfuscated classes.
        textarea = None
        for selector in [
            SELECTORS["post_textarea"],
            'div[contenteditable="true"][aria-label]',
            'div[contenteditable="true"]',
        ]:
            try:
                textarea = page.wait_for_selector(selector, state="visible", timeout=8_000)
                if textarea:
                    logger.debug("Found post textarea with selector: %s", selector)
                    break
            except Exception:
                continue

        if not textarea:
            logger.warning("Post textarea did not appear after composer click.")
            return False

        textarea.click()
        human_delay(0.3, 0.6)
        page.keyboard.type(content, delay=30)
        human_delay(1.0, 2.0)

        # Find and click the Post submit button.
        post_btn = None
        for selector in [
            SELECTORS["post_submit"],
            'div[aria-label="Post"][role="button"]',
            'div[role="button"]:has-text("Post")',
            'span[role="button"]:has-text("Post")',
        ]:
            try:
                post_btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if post_btn:
                    logger.debug("Found Post button with selector: %s", selector)
                    break
            except Exception:
                continue

        if not post_btn:
            logger.warning("Post submit button not found.")
            return False

        post_btn.click()
        human_delay(3.0, 5.0)
        logger.info("Successfully created Facebook post (%d chars).", len(content))
        return True

    except Exception:
        logger.exception("Error creating Facebook post")
        return False


def execute_facebook_post(
    content: str,
    session_path: str | Path | None = None,
) -> bool:
    """Create an original Facebook wall post.

    Returns True on success, False on any failure.
    """
    _session = Path(session_path) if session_path else DEFAULT_SESSION_PATH

    if not content.strip():
        logger.error("Post content is empty — nothing to post.")
        return False

    if not _session.exists():
        logger.error(
            "Facebook session file not found at %s. "
            "Run 'python browser/facebook_setup.py' to log in first.",
            _session,
        )
        return False

    pw = None
    browser = None
    try:
        pw = create_playwright_instance()
        browser, context = launch_browser(pw, headless=True, session_path=_session)
        page = context.new_page()

        logger.info("Warming up session — navigating to Facebook home...")
        if not check_login_state(page):
            logger.error("Not logged in. Run 'python browser/facebook_setup.py'.")
            return False

        human_delay(2.5, 4.0)
        dismiss_overlays(page)

        success = _do_facebook_post(page, content)
        save_session(context, _session)
        return success

    except Exception:
        logger.exception("Error executing Facebook post")
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
