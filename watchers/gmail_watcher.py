"""
gmail_watcher.py - Individual Watcher / Sense Component

Responsibility:
- Connects to Gmail via OAuth 2.0 and polls for new/important unread emails
- Creates a structured Markdown file in AI_Employee_Vault/Needs_Action/ for each
  detected email containing metadata, a neutral summary, and full content
- Tracks already-processed message IDs to avoid duplicates (persisted to disk)

Boundary:
- READ-ONLY access to Gmail — must NEVER send, reply to, or modify emails
- Does NOT reason, plan, approve, or execute actions
- Does NOT trigger the orchestrator directly; communication is file-based only

Assumptions:
- OAuth credentials file exists at ./credentials/gmail_token.json
  (generated via Google Cloud Console OAuth flow for the Gmail readonly scope)
- If the token expires, google-auth will auto-refresh using the refresh token
- The vault path is resolved relative to this script's parent directory
"""

import json
import logging
import re
import sys
import base64
from datetime import datetime
from pathlib import Path

import socket
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Add parent dir to path so base_watcher can be imported when run standalone
sys.path.insert(0, str(Path(__file__).resolve().parent))
from base_watcher import BaseWatcher

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
CREDENTIALS_PATH = BASE_DIR / "credentials" / "gmail_token.json"
PROCESSED_IDS_PATH = BASE_DIR / "credentials" / ".gmail_processed_ids.json"

# Gmail API read-only scope — enforces that this watcher can never send mail
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CHECK_INTERVAL = 120  # seconds between polls

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "gmail_watcher.log", encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("gmail_watcher")


# ---------------------------------------------------------------------------
# Helper: sanitize filenames
# ---------------------------------------------------------------------------

def _sanitize_filename(text: str, max_len: int = 60) -> str:
    """Remove characters unsafe for filenames and truncate."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text)
    return text.strip()[:max_len]


# ---------------------------------------------------------------------------
# Helper: decode email body
# ---------------------------------------------------------------------------

def _decode_body(payload: dict) -> str:
    """Recursively extract plain-text body from Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    # Fallback: recurse into nested parts
    for part in parts:
        result = _decode_body(part)
        if result:
            return result
    return ""


# ---------------------------------------------------------------------------
# GmailWatcher
# ---------------------------------------------------------------------------

class GmailWatcher(BaseWatcher):
    def __init__(self):
        super().__init__(vault_path=str(VAULT_PATH), check_interval=CHECK_INTERVAL)
        self.service = None
        self.processed_ids: set[str] = set()
        self._load_processed_ids()
        self._connect()

    # -- Gmail connection ----------------------------------------------------

    def _connect(self):
        """Authenticate with Gmail using OAuth credentials."""
        if not CREDENTIALS_PATH.exists():
            logger.error(
                "Gmail credentials not found at %s. "
                "Run the OAuth setup flow first to generate gmail_token.json.",
                CREDENTIALS_PATH,
            )
            raise FileNotFoundError(f"Missing credentials: {CREDENTIALS_PATH}")

        creds = Credentials.from_authorized_user_file(str(CREDENTIALS_PATH), SCOPES)

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail token...")
            creds.refresh(Request())
            # Persist refreshed token
            CREDENTIALS_PATH.write_text(creds.to_json())
            logger.info("Token refreshed and saved.")

        # Set a global socket timeout so API calls can't hang forever
        socket.setdefaulttimeout(30)
        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Connected to Gmail API (readonly, 30s socket timeout).")

    # -- Processed ID persistence --------------------------------------------

    def _load_processed_ids(self):
        if PROCESSED_IDS_PATH.exists():
            try:
                data = json.loads(PROCESSED_IDS_PATH.read_text())
                self.processed_ids = set(data)
                logger.info("Loaded %d processed message IDs.", len(self.processed_ids))
            except Exception:
                logger.exception("Failed to load processed IDs; starting fresh.")
                self.processed_ids = set()

    def _save_processed_ids(self):
        PROCESSED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROCESSED_IDS_PATH.write_text(json.dumps(list(self.processed_ids)))

    # -- BaseWatcher interface -----------------------------------------------

    def check_for_updates(self) -> list:
        """Fetch unread important messages not yet processed."""
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q="is:unread category:primary newer_than:2d", maxResults=20)
            .execute()
        )
        messages = results.get("messages", [])
        new_messages = [m for m in messages if m["id"] not in self.processed_ids]
        if new_messages:
            logger.info("Found %d new message(s) to process.", len(new_messages))
        return new_messages

    def create_action_file(self, message) -> Path:
        """Fetch message metadata and write a structured Markdown file."""
        logger.info("Fetching email %s ...", message["id"])

        # First fetch metadata (fast, never hangs)
        msg = (
            self.service.users()
            .messages()
            .get(userId="me", id=message["id"], format="metadata",
                 metadataHeaders=["From", "Subject", "Date", "Message-ID"])
            .execute()
        )

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        sender = headers.get("From", "Unknown")
        subject = headers.get("Subject", "(No Subject)")
        date = headers.get("Date", "Unknown")
        message_id = headers.get("Message-ID", message["id"])
        snippet = msg.get("snippet", "")

        # Try to get full body, but don't block if it fails
        body = ""
        try:
            full_msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=message["id"], format="full")
                .execute()
            )
            body = _decode_body(full_msg["payload"])
        except Exception:
            logger.warning("Could not fetch full body for %s, using snippet", message["id"])

        # Build structured Markdown content
        safe_subject = _sanitize_filename(subject)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"EMAIL_{timestamp}_{safe_subject}.md"

        content = f"""---
type: email
source: gmail
message_id: "{message["id"]}"
from: "{sender}"
subject: "{subject}"
date: "{date}"
received_at: "{datetime.now().isoformat()}"
status: pending
---

# Email: {subject}

## Metadata
| Field     | Value |
|-----------|-------|
| From      | {sender} |
| Subject   | {subject} |
| Date      | {date} |
| Gmail ID  | {message["id"]} |

## Summary
{snippet}

## Full Content
{body if body else snippet}

## Raw Reference
- Gmail Message ID: `{message["id"]}`
- Original Message-ID header: `{message_id}`
"""

        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")

        # Track as processed and persist
        self.processed_ids.add(message["id"])
        self._save_processed_ids()

        return filepath


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("gmail_watcher.py starting — Gmail Sense Component")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Credentials: %s", CREDENTIALS_PATH)
    logger.info("Poll interval: %ds", CHECK_INTERVAL)
    logger.info("=" * 60)

    watcher = GmailWatcher()
    watcher.run()


if __name__ == "__main__":
    main()
