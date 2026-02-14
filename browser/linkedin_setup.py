"""
linkedin_setup.py - One-time interactive login for LinkedIn browser automation.

Usage:
    python browser/linkedin_setup.py

What it does:
1. Launches a VISIBLE (headed) Chromium browser
2. Navigates to linkedin.com/login
3. Waits for the user to log in manually (up to 5 minutes)
4. Exports the session (cookies + localStorage) to credentials/linkedin_session.json
5. Verifies the saved session by checking for the logged-in nav element

After this, the linkedin_watcher and linkedin_actions modules can use the saved
session to operate headlessly without needing API keys or credentials in code.
"""

import sys
import time
from pathlib import Path

# Ensure project root is on path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.linkedin_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    check_login_state,
    SELECTORS,
)

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_PATH = BASE_DIR / "credentials" / "linkedin_session.json"


def main():
    print("=" * 60)
    print("LinkedIn Browser Login Setup")
    print("=" * 60)
    print()
    print(f"Session will be saved to: {SESSION_PATH}")
    print()
    print("A browser window will open. Please:")
    print("  1. Log in to your LinkedIn account")
    print("  2. Complete any 2FA / CAPTCHA if prompted")
    print("  3. Wait until you see your main LinkedIn feed")
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
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60_000)

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
                nav_me = page.query_selector(SELECTORS["nav_me"])
                if nav_me:
                    logged_in = True
                    break

                # Also check if we're already on the feed
                if "/feed" in page.url:
                    page.wait_for_selector(SELECTORS["nav_me"], timeout=5_000)
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

        # Verify by opening a new headless context with the saved session
        print("Verifying saved session...")
        browser2, context2 = launch_browser(pw, headless=True, session_path=SESSION_PATH)
        verify_page = context2.new_page()
        verified = check_login_state(verify_page, timeout=15_000)
        browser2.close()

        if verified:
            print("Session verification PASSED — you're all set!")
            print()
            print("Next steps:")
            print("  - The linkedin_watcher will use this session automatically")
            print("  - Restart the supervisor: python main_watcher.py")
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
