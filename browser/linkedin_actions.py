"""
linkedin_actions.py - Browser-based LinkedIn action executor.

Responsibility:
- Executes approved LinkedIn actions (like, comment, post) via Playwright
- Launched as a short-lived browser session per action batch
- Called directly by orchestrator.py (not via subprocess)

Boundary:
- Only acts on explicitly approved actions
- Does NOT reason, plan, or decide — just executes
- Closes browser after each batch
"""

import logging
from pathlib import Path

from browser.linkedin_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    dismiss_cookie_consent,
    build_post_url,
    human_delay,
    SELECTORS,
)

logger = logging.getLogger("linkedin_actions")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SESSION_PATH = BASE_DIR / "credentials" / "linkedin_session.json"


def execute_linkedin_actions(
    post_urn: str,
    author_username: str,
    actions: list[str],
    comment_text: str = "",
    session_path: str | Path | None = None,
) -> dict[str, bool]:
    """Execute a list of LinkedIn actions for a specific post via browser automation.

    Args:
        post_urn: The LinkedIn activity URN (e.g. 'urn:li:activity:1234567890').
        author_username: The post author's LinkedIn username slug (for logging).
        actions: List of action strings: "like", "comment", "ignore".
        comment_text: Text to post as a comment (required if "comment" in actions).
        session_path: Path to the session JSON file.

    Returns:
        Dict mapping action name → success boolean.
    """
    session_path = Path(session_path) if session_path else DEFAULT_SESSION_PATH
    results: dict[str, bool] = {}

    if not session_path.exists():
        logger.error(
            "Session file not found at %s. Run browser/linkedin_setup.py first.",
            session_path,
        )
        return {a: False for a in actions}

    # Filter out ignore
    actionable = [a for a in actions if a != "ignore"]
    if not actionable:
        logger.info("No actionable items for post %s (ignore only).", post_urn)
        return {"ignore": True}

    pw = None
    browser = None
    try:
        pw = create_playwright_instance()
        browser, context = launch_browser(pw, headless=True, session_path=session_path)
        page = context.new_page()

        # Warm up: navigate to feed first so LinkedIn recognises the session
        logger.info("Warming up session — navigating to LinkedIn feed first...")
        if not check_login_state(page):
            logger.error(
                "Not logged in after session restore. "
                "Run browser/linkedin_setup.py to refresh the session."
            )
            return {a: False for a in actions}
        logger.info("Session verified. Proceeding to post.")
        human_delay(2.0, 3.0)

        # Navigate to the specific post permalink
        post_url = build_post_url(post_urn)
        logger.info("Navigating to %s", post_url)
        page.goto(post_url, wait_until="domcontentloaded", timeout=60_000)
        human_delay(2.0, 4.0)

        _dismiss_overlays(page)
        page.evaluate("window.scrollTo(0, 0)")
        human_delay(0.5, 1.0)

        # Wait for social action buttons to be present before attempting actions
        if not _wait_for_social_actions(page, post_urn, timeout=15_000):
            return {a: False for a in actionable}

        # Execute each action in order
        for action in actionable:
            if action == "like":
                results["like"] = _do_like(page, post_urn)
            elif action == "comment":
                results["comment"] = _do_comment(page, post_urn, comment_text)
            else:
                logger.warning("Unknown action '%s' for post %s", action, post_urn)
                results[action] = False

            human_delay(1.5, 3.0)

        # Save session to keep cookies fresh
        save_session(context, session_path)

    except Exception:
        logger.exception("Error executing actions for post %s", post_urn)
        for a in actionable:
            if a not in results:
                results[a] = False
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

    return results


def execute_linkedin_post(
    content: str,
    session_path: str | Path | None = None,
) -> bool:
    """Create an original LinkedIn post (not a comment on an existing post).

    Args:
        content: The text content of the new post.
        session_path: Path to the session JSON file.

    Returns:
        True if the post was submitted successfully, False otherwise.
    """
    session_path = Path(session_path) if session_path else DEFAULT_SESSION_PATH

    if not content:
        logger.error("No content provided for LinkedIn post.")
        return False

    if not session_path.exists():
        logger.error(
            "Session file not found at %s. Run browser/linkedin_setup.py first.",
            session_path,
        )
        return False

    pw = None
    browser = None
    try:
        pw = create_playwright_instance()
        browser, context = launch_browser(pw, headless=True, session_path=session_path)
        page = context.new_page()

        # check_login_state navigates to /feed/ — that's exactly where we need to be
        logger.info("Warming up session for new post — navigating to feed...")
        if not check_login_state(page):
            logger.error("Not logged in. Run browser/linkedin_setup.py.")
            return False

        # Give the feed extra time to settle — LinkedIn's Ember.js renders progressively
        # and delayed overlays (cookie prompts, premium upsell) can appear seconds after load.
        human_delay(3.0, 5.0)
        _dismiss_overlays(page)

        result = _do_post(page, content)
        save_session(context, session_path)
        return result

    except Exception:
        logger.exception("Error creating LinkedIn post")
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
# Overlay / consent dialog handling
# ---------------------------------------------------------------------------

def _dismiss_overlays(page) -> None:
    """Dismiss cookie consent and all blocking UI elements via JS and clicks."""
    try:
        dismiss_cookie_consent(page)

        # Click any visible close/dismiss buttons on dialogs (premium upsell, tooltips, etc.)
        page.evaluate("""
            () => {
                // Try clicking visible dismiss/close buttons first
                const clickSelectors = [
                    'button[aria-label="Dismiss"]',
                    'button[aria-label="Close"]',
                    'button[aria-label="Decline"]',
                    'button[data-test-modal-close-btn]',
                ];
                for (const sel of clickSelectors) {
                    const btn = document.querySelector(sel);
                    if (btn && btn.offsetParent !== null) {
                        try { btn.click(); } catch(e) {}
                    }
                }
                // Remove blocking overlay elements that intercept pointer events
                const removeSelectors = [
                    '.artdeco-modal-overlay',
                    '.contextual-sign-in-modal',
                    'div[data-test-modal-id]',
                    '.premium-upsell-modal',
                    '.msg-overlay-bubble-header',
                    '[data-test-premium-upsell-modal]',
                    '.cookie-consent-modal',
                ];
                for (const sel of removeSelectors) {
                    const el = document.querySelector(sel);
                    if (el) el.remove();
                }
            }
        """)
        human_delay(0.5, 1.0)
    except Exception:
        logger.debug("Error dismissing overlays", exc_info=True)


# ---------------------------------------------------------------------------
# Individual action implementations
# ---------------------------------------------------------------------------

def _wait_for_social_actions(page, post_urn: str, timeout: int = 15_000) -> bool:
    """Wait for the social action bar (Like/Comment buttons) to appear on the post page.

    Returns True if the bar appeared, False if it timed out.
    """
    try:
        page.wait_for_selector(
            f'{SELECTORS["like_button"]}, {SELECTORS["liked_button"]}, {SELECTORS["comment_button"]}',
            timeout=timeout,
        )
        return True
    except Exception:
        logger.warning(
            "Social action buttons did not appear on post %s within %dms — "
            "post may be deleted, restricted, or page did not fully load.",
            post_urn, timeout,
        )
        return False


def _do_like(page, post_urn: str) -> bool:
    """Click the Like reaction button on the current post page.

    Uses exact aria-label matches to avoid the substring collision between
    'React Like' (not yet liked) and 'Unreact Like' (already liked).
    """
    try:
        # Check if already liked — exact match on "Unreact Like"
        if page.query_selector(SELECTORS["liked_button"]):
            logger.info("Post %s is already liked.", post_urn)
            return True

        like_btn = page.query_selector(SELECTORS["like_button"])
        if not like_btn:
            logger.warning(
                "Like button ('React Like') not found for post %s. "
                "Post may already be liked or selector changed.",
                post_urn,
            )
            return False

        like_btn.click()
        human_delay(1.0, 2.0)

        # Verify — "Unreact Like" should now appear
        if page.query_selector(SELECTORS["liked_button"]):
            logger.info("Successfully liked post %s", post_urn)
            return True
        else:
            logger.warning("Like click did not register for post %s", post_urn)
            return False

    except Exception:
        logger.exception("Error liking post %s", post_urn)
        return False


def _do_comment(page, post_urn: str, comment_text: str) -> bool:
    """Click the Comment button, type a comment via keyboard events, and submit."""
    if not comment_text:
        logger.error("No comment text provided for post %s", post_urn)
        return False

    try:
        # Click the top-level "Comment" social action button to open the comment box
        comment_btn = page.query_selector(SELECTORS["comment_button"])
        if not comment_btn:
            logger.warning("Comment button not found for post %s", post_urn)
            return False

        comment_btn.click()
        human_delay(1.0, 2.0)

        # Wait for the Quill editor to appear
        try:
            editor = page.wait_for_selector(SELECTORS["comment_editor"], timeout=10_000)
        except Exception:
            logger.warning(
                "Comment editor ('%s') did not appear for post %s",
                SELECTORS["comment_editor"], post_urn,
            )
            return False

        _dismiss_overlays(page)

        # Focus the editor and type using keyboard events.
        # LinkedIn's Quill editor requires real keystroke events — fill() sets
        # innerText directly and does not trigger Quill's internal state, so the
        # submit button stays disabled and the text may not render correctly.
        editor.click()
        human_delay(0.3, 0.6)
        page.keyboard.type(comment_text, delay=30)  # 30ms between keystrokes feels human
        human_delay(0.8, 1.5)

        _dismiss_overlays(page)

        # The submit button becomes enabled only after text is present in the editor.
        try:
            submit_btn = page.wait_for_selector(
                f"{SELECTORS['comment_submit']}:not([disabled])",
                timeout=8_000,
            )
        except Exception:
            logger.warning(
                "Comment submit button did not become enabled for post %s — "
                "text may not have registered in the editor",
                post_urn,
            )
            return False

        submit_btn.click()
        human_delay(2.0, 4.0)
        logger.info("Successfully commented on post %s", post_urn)
        return True

    except Exception:
        logger.exception("Error commenting on post %s", post_urn)
        return False


def _do_post(page, content: str) -> bool:
    """Create a new original LinkedIn post from the feed page.

    Relies on the page already being on /feed/ (guaranteed by execute_linkedin_post).
    The 'Start a post' button has no aria-label — matched by visible text.
    The post submit button is disabled until text is entered in the editor.
    """
    try:
        # Wait explicitly for the "Start a post" button to be present and stable.
        # LinkedIn's Ember.js renders components progressively — the button may flicker
        # or be temporarily intercepted by delayed overlays (cookie prompts, premium upsell).
        try:
            page.wait_for_selector(
                SELECTORS["start_post_trigger"],
                state="visible",
                timeout=15_000,
            )
        except Exception:
            logger.warning("'Start a post' button did not appear on feed within 15s.")
            return False

        # Dismiss any overlays that appeared after the feed loaded
        _dismiss_overlays(page)
        human_delay(0.5, 1.0)

        # Click "Start a post" — button has no aria-label, use text-based Playwright locator
        trigger = page.locator(SELECTORS["start_post_trigger"]).first
        try:
            trigger.click(timeout=10_000)
        except Exception:
            # JS click as fallback — bypasses pointer-event interception
            logger.debug("Locator click failed; trying JS click on 'Start a post'.")
            try:
                page.evaluate("""
                    () => {
                        const btns = [...document.querySelectorAll('button')];
                        const btn = btns.find(b => b.innerText.trim().includes('Start a post'));
                        if (btn) btn.click();
                        else throw new Error('Start a post button not found in DOM');
                    }
                """)
            except Exception:
                logger.warning("'Start a post' button could not be clicked.")
                return False

        human_delay(1.5, 2.5)

        # Scope all interactions to the share modal — the feed page already contains
        # comment-box Quill editors with the same aria-label, which confuse an
        # unscoped locator and cause click timeouts.
        modal_loc = page.locator(".share-box-v2__modal, .share-creation-state")
        try:
            modal_loc.first.wait_for(state="visible", timeout=10_000)
        except Exception:
            logger.warning("Post compose modal did not appear.")
            return False

        # Editor scoped to the modal
        editor_loc = modal_loc.first.locator(".ql-editor").first
        try:
            editor_loc.wait_for(state="visible", timeout=8_000)
        except Exception:
            logger.warning("Post compose textarea did not appear inside modal.")
            return False

        # Type content using keyboard events (Quill requires keystrokes, not fill)
        editor_loc.click()
        human_delay(0.3, 0.6)
        page.keyboard.type(content, delay=25)
        human_delay(1.0, 2.0)

        # Post submit scoped to modal — disabled until text is present
        post_btn_loc = modal_loc.first.locator(
            f"{SELECTORS['post_submit']}:not([disabled])"
        )
        try:
            post_btn_loc.wait_for(state="visible", timeout=8_000)
        except Exception:
            logger.warning(
                "Post submit button did not become enabled — "
                "text may not have registered in the editor"
            )
            return False

        post_btn_loc.click()
        human_delay(3.0, 5.0)
        logger.info("Successfully created LinkedIn post (%d chars).", len(content))
        return True

    except Exception:
        logger.exception("Error creating LinkedIn post")
        return False
