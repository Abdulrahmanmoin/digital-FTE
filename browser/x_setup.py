"""
x_setup.py - One-time interactive login for X/Twitter browser automation.

Usage:
    python browser/x_setup.py

What it does:
1. Launches a VISIBLE (headed) Chromium browser
2. Navigates to x.com/login
3. Waits for the user to log in manually
4. Exports the session (cookies + localStorage) to credentials/x_session.json
5. Verifies login by checking for the compose tweet button

After this, the x_watcher and x_actions modules can use the saved session
to operate headlessly without needing API keys.
"""

import sys
import time
from pathlib import Path

# Ensure project root is on path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.x_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    SELECTORS,
)

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_PATH = BASE_DIR / "credentials" / "x_session.json"


def main():
    print("=" * 60)
    print("X/Twitter Browser Login Setup")
    print("=" * 60)
    print()
    print(f"Session will be saved to: {SESSION_PATH}")
    print()
    print("A browser window will open. Please:")
    print("  1. Log in to your X/Twitter account")
    print("  2. Complete any 2FA if prompted")
    print("  3. Wait until you see the home timeline")
    print("  4. Come back here — the script will detect the login")
    print()

    pw = None
    browser = None
    try:
        pw = create_playwright_instance()
        # Headed mode — user needs to see and interact
        browser, context = launch_browser(pw, headless=False, session_path=None)
        page = context.new_page()

        # Navigate to login page
        page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=60_000)

        print("Browser opened. Waiting for you to log in...")
        print("(This will timeout after 5 minutes)")
        print()

        # Poll for login state — check every 3 seconds for up to 5 minutes
        logged_in = False
        max_wait = 300  # 5 minutes
        elapsed = 0
        check_interval = 3

        while elapsed < max_wait:
            time.sleep(check_interval)
            elapsed += check_interval

            try:
                # Try navigating to home and checking for compose button
                compose = page.query_selector(SELECTORS["compose_button"])
                if compose:
                    logged_in = True
                    break

                # Also check if we're on the home page now (user may have navigated)
                if "/home" in page.url:
                    page.wait_for_selector(SELECTORS["compose_button"], timeout=5_000)
                    logged_in = True
                    break
            except Exception:
                pass  # Not logged in yet

            if elapsed % 15 == 0:
                print(f"  Still waiting... ({elapsed}s elapsed)")

        if not logged_in:
            print()
            print("ERROR: Login not detected within 5 minutes.")
            print("Please try again.")
            return

        # Save session
        save_session(context, SESSION_PATH)

        print()
        print("Login detected! Session saved.")
        print(f"Session file: {SESSION_PATH}")
        print()

        # Verify by opening a new context with the saved session
        print("Verifying saved session...")
        browser2, context2 = launch_browser(pw, headless=True, session_path=SESSION_PATH)
        verify_page = context2.new_page()
        verified = check_login_state(verify_page, timeout=15_000)
        browser2.close()

        if verified:
            print("Session verification PASSED — you're all set!")
            print()
            print("Next steps:")
            print("  - The x_watcher will use this session automatically")
            print("  - Restart PM2: pm2 restart ai-employee")
        else:
            print("WARNING: Session verification failed.")
            print("The session was saved but may not work headlessly.")
            print("Try running this setup again.")

    except KeyboardInterrupt:
        print("\nSetup cancelled by user.")
    except Exception as e:
        print(f"\nERROR: {e}")
        raise
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


if __name__ == "__main__":
    main()
