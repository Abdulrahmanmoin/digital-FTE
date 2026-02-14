"""
x_actions.py - Browser-based X/Twitter action executor.

Responsibility:
- Executes approved tweet actions (like, retweet, reply) via Playwright
- Launched as a short-lived browser session per action batch
- Called directly by orchestrator.py (not via subprocess)

Boundary:
- Only acts on explicitly approved actions
- Does NOT reason, plan, or decide — just executes
- Closes browser after each batch
"""

import logging
from datetime import datetime
from pathlib import Path

from browser.x_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    human_delay,
    SELECTORS,
)

logger = logging.getLogger("x_actions")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SESSION_PATH = BASE_DIR / "credentials" / "x_session.json"


def execute_tweet_actions(
    tweet_id: str,
    author_username: str,
    actions: list[str],
    reply_text: str = "",
    session_path: str | Path | None = None,
) -> dict[str, bool]:
    """Execute a list of tweet actions via browser automation.

    Args:
        tweet_id: The tweet ID to act on.
        author_username: The tweet author's username (for URL construction).
        actions: List of action strings: "like", "retweet", "reply", "ignore".
        reply_text: Text to post as a reply (required if "reply" in actions).
        session_path: Path to the session JSON file.

    Returns:
        Dict mapping action name → success boolean.
    """
    session_path = Path(session_path) if session_path else DEFAULT_SESSION_PATH
    results: dict[str, bool] = {}

    if not session_path.exists():
        logger.error("Session file not found at %s. Run browser/x_setup.py first.", session_path)
        return {a: False for a in actions}

    # Filter out ignore
    actionable = [a for a in actions if a != "ignore"]
    if not actionable:
        logger.info("No actionable items for tweet %s (ignore only).", tweet_id)
        return {"ignore": True}

    pw = None
    browser = None
    try:
        pw = create_playwright_instance()
        browser, context = launch_browser(pw, headless=True, session_path=session_path)
        page = context.new_page()

        # Warm up: navigate to home first so X recognises the session before
        # we deep-link into a specific tweet. Skipping this causes timeouts or
        # interstitial pages on cold browser starts.
        logger.info("Warming up session — navigating to x.com/home first...")
        if not check_login_state(page):
            logger.error(
                "Not logged in after session restore. "
                "Run browser/x_setup.py to refresh the session."
            )
            return {a: False for a in actions}
        logger.info("Session verified. Proceeding to tweet.")
        human_delay(2.0, 3.0)

        # Navigate to the tweet
        tweet_url = f"https://x.com/{author_username}/status/{tweet_id}"
        logger.info("Navigating to %s", tweet_url)
        page.goto(tweet_url, wait_until="domcontentloaded", timeout=60_000)
        human_delay(2.0, 4.0)

        # Dismiss any overlays (cookie consent, etc.) that block the page
        _dismiss_overlays(page)

        # Scroll to top to ensure the tweet article is in view
        page.evaluate("window.scrollTo(0, 0)")
        human_delay(0.5, 1.0)

        # Wait for the tweet to load
        try:
            page.wait_for_selector(SELECTORS["tweet_article"], timeout=30_000)
        except Exception:
            logger.error(
                "Tweet page did not load properly for %s (title=%r, url=%r)",
                tweet_url, page.title(), page.url,
            )
            return {a: False for a in actions}

        # Execute each action
        for action in actionable:
            if action == "like":
                results["like"] = _do_like(page, tweet_id)
            elif action == "retweet":
                results["retweet"] = _do_retweet(page, tweet_id)
            elif action == "reply":
                results["reply"] = _do_reply(page, tweet_id, reply_text)
            else:
                logger.warning("Unknown action '%s' for tweet %s", action, tweet_id)
                results[action] = False

            human_delay(1.0, 2.5)

        # Save session to keep cookies fresh
        save_session(context, session_path)

    except Exception:
        logger.exception("Error executing actions for tweet %s", tweet_id)
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


# ---------------------------------------------------------------------------
# Overlay / consent dialog handling
# ---------------------------------------------------------------------------

def _dismiss_overlays(page) -> None:
    """Dismiss cookie consent overlays and other blocking UI elements."""
    try:
        mask = page.query_selector('[data-testid="twc-cc-mask"]')
        if not mask:
            return

        logger.info("Cookie consent overlay detected — attempting to dismiss...")

        # Try clicking a visible dismiss/accept button near the overlay
        for selector in [
            '[data-testid="BottomBar"] button:last-child',
            '[data-testid="BottomBar"] button',
            'button[data-testid="close"]',
        ]:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    human_delay(0.5, 1.0)
                    logger.info("Dismissed overlay via %s", selector)
                    return
            except Exception:
                continue

        # Fallback: remove the overlay elements via JavaScript so they no
        # longer intercept pointer events.
        logger.info("No dismiss button found — removing overlay via JS")
        page.evaluate("""
            () => {
                const sel = ['[data-testid="twc-cc-mask"]', '[data-testid="BottomBar"]'];
                sel.forEach(s => { const el = document.querySelector(s); if (el) el.remove(); });
            }
        """)
        human_delay(0.3, 0.6)
    except Exception:
        logger.warning("Error dismissing overlays", exc_info=True)


# ---------------------------------------------------------------------------
# Individual action implementations
# ---------------------------------------------------------------------------

def _do_like(page, tweet_id: str) -> bool:
    """Click the like button on the current tweet page."""
    try:
        # Check if already liked
        unlike_btn = page.query_selector(SELECTORS["unlike_button"])
        if unlike_btn:
            logger.info("Tweet %s is already liked.", tweet_id)
            return True

        like_btn = page.query_selector(SELECTORS["like_button"])
        if not like_btn:
            logger.warning("Like button not found for tweet %s", tweet_id)
            return False

        like_btn.click()
        human_delay(1.0, 2.0)

        # Verify — unlike button should appear
        unlike_btn = page.query_selector(SELECTORS["unlike_button"])
        if unlike_btn:
            logger.info("Successfully liked tweet %s", tweet_id)
            return True
        else:
            logger.warning("Like click did not register for tweet %s", tweet_id)
            return False

    except Exception:
        logger.exception("Error liking tweet %s", tweet_id)
        return False


def _do_retweet(page, tweet_id: str) -> bool:
    """Click the retweet button and confirm."""
    try:
        # Check if already retweeted
        unretweet_btn = page.query_selector(SELECTORS["unretweet_button"])
        if unretweet_btn:
            logger.info("Tweet %s is already retweeted.", tweet_id)
            return True

        retweet_btn = page.query_selector(SELECTORS["retweet_button"])
        if not retweet_btn:
            logger.warning("Retweet button not found for tweet %s", tweet_id)
            return False

        retweet_btn.click()
        human_delay(0.5, 1.5)

        # Click the confirm "Repost" option in the dropdown
        try:
            confirm_btn = page.wait_for_selector(
                SELECTORS["retweet_confirm"], timeout=5_000
            )
            if confirm_btn:
                confirm_btn.click()
                human_delay(1.0, 2.0)
                logger.info("Successfully retweeted tweet %s", tweet_id)
                return True
        except Exception:
            logger.warning("Retweet confirm button not found for tweet %s", tweet_id)
            return False

    except Exception:
        logger.exception("Error retweeting tweet %s", tweet_id)
        return False


def _do_reply(page, tweet_id: str, reply_text: str) -> bool:
    """Click the reply button, type the reply, and submit."""
    if not reply_text:
        logger.error("No reply text provided for tweet %s", tweet_id)
        return False

    try:
        # Click the reply button on the tweet
        reply_btn = page.query_selector(SELECTORS["reply_button"])
        if not reply_btn:
            logger.warning("Reply button not found for tweet %s", tweet_id)
            return False

        reply_btn.click()
        human_delay(1.0, 2.0)

        # Wait for the reply textarea to appear
        try:
            textarea = page.wait_for_selector(
                SELECTORS["tweet_textarea"], timeout=10_000
            )
        except Exception:
            logger.warning("Reply textarea did not appear for tweet %s", tweet_id)
            return False

        # Dismiss any overlays before interacting with the textarea
        _dismiss_overlays(page)

        # Focus and fill the textarea. Use JS dispatch as a fallback if the
        # normal Playwright fill is blocked by a residual overlay.
        try:
            textarea.click()
            human_delay(0.3, 0.8)
            textarea.fill(reply_text)
        except Exception:
            logger.info("Direct fill blocked — using JS fallback for textarea")
            page.evaluate(
                """(args) => {
                    const el = document.querySelector('[data-testid="tweetTextarea_0"]');
                    if (el) {
                        el.focus();
                        const nativeInputSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLElement.prototype, 'innerText') ||
                            Object.getOwnPropertyDescriptor(window.Element.prototype, 'innerHTML');
                        el.dispatchEvent(new Event('focus'));
                    }
                }""",
                None
            )
            textarea.fill(reply_text)
        human_delay(0.5, 1.5)

        # Dismiss overlays again before submitting (they can reappear)
        _dismiss_overlays(page)

        # Click the submit button — use JS click as fallback if pointer intercepted
        submit_btn = page.query_selector(SELECTORS["tweet_submit"])
        if not submit_btn:
            logger.warning("Tweet submit button not found for tweet %s", tweet_id)
            return False

        try:
            submit_btn.click()
        except Exception:
            logger.info("Direct click blocked — using JS click for submit button")
            page.evaluate("document.querySelector('[data-testid=\"tweetButton\"]')?.click()")
        human_delay(2.0, 4.0)

        logger.info("Successfully replied to tweet %s", tweet_id)
        return True

    except Exception:
        logger.exception("Error replying to tweet %s", tweet_id)
        return False
