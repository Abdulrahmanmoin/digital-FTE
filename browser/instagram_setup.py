"""
instagram_setup.py - One-Time Interactive Login for Instagram

Run this script ONCE to log in to Instagram manually through a visible browser
window. The session is saved to credentials/instagram_session.json and reused
by instagram_watcher.py and instagram_actions.py.

Usage:
    python browser/instagram_setup.py

Steps:
    1. A browser window will open pointing to Instagram.
    2. Log in with your Instagram credentials (and complete 2FA if prompted).
    3. Once you see the home/inbox page, come back to this terminal and press Enter.
    4. The session is saved. You can close the browser.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.instagram_browser import (
    create_playwright_instance,
    launch_browser,
    save_session,
    INBOX_URL,
)

SESSION_PATH = Path(__file__).resolve().parent.parent / "credentials" / "instagram_session.json"


def main():
    print("=" * 60)
    print("Instagram Session Setup")
    print("=" * 60)
    print()
    print("A browser window will open. Log in to Instagram manually.")
    print("Complete any 2FA or verification steps.")
    print("Once you are on the Home or DM inbox page, come back here")
    print("and press Enter to save the session.")
    print()

    pw = create_playwright_instance()
    browser, context = launch_browser(pw, headless=False)
    page = context.new_page()

    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")

    input("Press Enter after you have logged in successfully... ")

    save_session(context, SESSION_PATH)
    print(f"\nSession saved to: {SESSION_PATH}")
    print("You can now close the browser and run main_watcher.py.")

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
