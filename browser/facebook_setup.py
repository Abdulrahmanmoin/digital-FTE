"""
facebook_setup.py - One-time interactive Facebook login script.

Run this script once to log in to Facebook via a headed browser window.
The session (cookies + localStorage) is saved to:
    credentials/facebook_session.json

Usage:
    python browser/facebook_setup.py

After saving the session, restart main_watcher.py / PM2 to activate the
Facebook watcher.

Notes:
- Session files are tied to the browser context — do NOT share them between
  machines or mix with other users' sessions.
- If your session expires, run this script again.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.facebook_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
)

SESSION_PATH = Path(__file__).resolve().parent.parent / "credentials" / "facebook_session.json"
LOGIN_URL = "https://www.facebook.com/login"
LOGIN_TIMEOUT_MINUTES = 5


def main():
    print("=" * 60)
    print("Facebook Session Setup")
    print("=" * 60)
    print(f"Session will be saved to: {SESSION_PATH}")
    print()
    print("A browser window will open. Log in to Facebook normally.")
    print(f"You have {LOGIN_TIMEOUT_MINUTES} minutes.")
    print()

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    pw = create_playwright_instance()
    try:
        browser, context = launch_browser(pw, headless=False, session_path=None)
        page = context.new_page()

        print("Opening Facebook login page...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        print()
        print("Log in to Facebook in the browser window that opened.")
        print()
        print(">>> Press ENTER here once you can see your Facebook home feed <<<")
        print("    (or wait — the script also detects login automatically)")
        print()

        import threading

        enter_pressed = threading.Event()

        def _wait_for_enter():
            try:
                input()
            except Exception:
                pass
            enter_pressed.set()

        t = threading.Thread(target=_wait_for_enter, daemon=True)
        t.start()

        logged_in = False
        deadline = time.time() + LOGIN_TIMEOUT_MINUTES * 60

        # Poll every second — check BOTH url change AND enter key.
        # NOTE: wait_for_url() is NOT used because it blocks the main thread and
        # prevents the Enter-key fallback from ever being reached.
        while time.time() < deadline:
            # Check if user pressed Enter
            if enter_pressed.is_set():
                print("\n  Enter pressed — saving session now.")
                time.sleep(2)
                logged_in = True
                break

            # Auto-detect: URL moved away from login page
            try:
                url = page.url
                path = url.split("?")[0].split("#")[0]  # strip query + fragment
                if (
                    "facebook.com" in url
                    and "/login" not in path
                    and "/checkpoint" not in path
                ):
                    print(f"\n  Auto-detected login at: {url}")
                    print("  Waiting 3s for cookies to settle...")
                    time.sleep(3)
                    logged_in = True
                    break
            except Exception:
                pass

            time.sleep(1)

        if not logged_in:
            print(f"\n  Timeout reached ({LOGIN_TIMEOUT_MINUTES} minutes).")

        if logged_in:
            save_session(context, SESSION_PATH)
            print()
            print(f"Login successful! Session saved to: {SESSION_PATH}")
            print()
            print("Next steps:")
            print("  1. Restart main_watcher.py or PM2 to activate the Facebook watcher.")
            print("  2. Check logs/facebook_watcher.log to verify it starts cleanly.")
        else:
            print()
            print(f"Timeout reached ({LOGIN_TIMEOUT_MINUTES} minutes). Did you log in?")
            print("Run this script again when ready.")

        browser.close()
    finally:
        pw.stop()


if __name__ == "__main__":
    main()
