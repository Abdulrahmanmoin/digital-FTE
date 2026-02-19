"""
orchestrator.py - System Coordinator / Manager

Responsibility:
- Monitors AI_Employee_Vault/Needs_Action/ for new task files
- Triggers Claude Code (terminal-based reasoning agent) to:
    - Read the task file
    - Create a structured plan in /Plans
    - Identify sensitive steps
    - Create approval request files in /Pending_Approval
- Monitors AI_Employee_Vault/Approved/ for human-approved action files
- Executes approved actions (e.g., sending emails via Gmail MCP through Claude Code)
- Moves completed files to /Done for audit trail

Boundary:
- Does NOT perform reasoning or planning itself (delegates to Claude Code)
- Does NOT connect to Gmail for reading emails (that's gmail_watcher's job)
- Only sends emails AFTER explicit human approval (file in /Approved)
- All actions are logged

Assumptions:
- Claude Code CLI (`claude`) is available on PATH
- Gmail MCP server is configured in Claude Code's MCP settings for sending emails
- The orchestrator itself never connects to Gmail — it delegates sending to Claude + MCP
- Human approval = moving a file from Pending_Approval/ to Approved/
- Approved action files contain YAML frontmatter with action type and parameters
"""

import concurrent.futures
import json
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from browser.x_actions import execute_tweet_actions as browser_execute_tweet_actions
from browser.linkedin_actions import (
    execute_linkedin_actions as browser_execute_linkedin_actions,
    execute_linkedin_post as browser_execute_linkedin_post,
)
from browser.instagram_actions import execute_instagram_reply as browser_execute_instagram_reply
from browser.facebook_actions import (
    execute_facebook_reply as browser_execute_facebook_reply,
    execute_facebook_post as browser_execute_facebook_post,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"

NEEDS_ACTION_DIR = VAULT_PATH / "Needs_Action"
PLANS_DIR = VAULT_PATH / "Plans"
PENDING_APPROVAL_DIR = VAULT_PATH / "Pending_Approval"
APPROVED_DIR = VAULT_PATH / "Approved"
DONE_DIR = VAULT_PATH / "Done"

POLL_INTERVAL = 15  # seconds between folder scans
MAX_REASONING_PER_CYCLE = 3  # max Claude Code calls before checking Approved/
BROWSER_ACTION_TIMEOUT = 150  # seconds before killing a hung browser action
CLAUDE_CMD = "claude"  # Claude Code CLI command

# LinkedIn rate limits
LINKEDIN_DAILY_ACTION_LIMIT = 5    # max like+comment actions per 24h window
LINKEDIN_POST_INTERVAL_HOURS = 1   # generate a new post draft every N hours

# X/Twitter rate limits
X_DAILY_ACTION_LIMIT = 5           # max reply/like/retweet actions per 24h window

# Instagram rate limits
INSTAGRAM_DAILY_ACTION_LIMIT = 5   # max DM replies per 24h window

# Facebook rate limits
FACEBOOK_DAILY_ACTION_LIMIT = 5    # max DM replies per 24h window
FACEBOOK_POST_INTERVAL_HOURS = 2   # generate a new post draft every N hours

CREDENTIALS_DIR = BASE_DIR / "credentials"
LINKEDIN_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".linkedin_daily_actions.json"
LINKEDIN_LAST_POST_PATH = CREDENTIALS_DIR / ".linkedin_last_post.json"
X_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".x_daily_actions.json"
INSTAGRAM_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".instagram_daily_actions.json"
FACEBOOK_DAILY_ACTIONS_PATH = CREDENTIALS_DIR / ".facebook_daily_actions.json"
FACEBOOK_LAST_POST_PATH = CREDENTIALS_DIR / ".facebook_last_post.json"

# Session alert config
# Change SESSION_ALERT_EMAIL to the address you want alerts sent to.
SESSION_ALERT_EMAIL = "arahmanmoin1@gmail.com"
SESSION_ALERT_COOLDOWN_HOURS = 24   # min hours between alerts for the same platform
SESSION_FAILURE_THRESHOLD = 2       # consecutive failures before alerting
SESSION_ALERTS_STATE_PATH = CREDENTIALS_DIR / ".session_alerts.json"

# Dedicated working directory for all orchestrator-triggered Claude invocations.
# Claude Code scopes conversation history by cwd, so using a subdirectory here
# keeps orchestrator sessions isolated from the developer's /resume history.
ORCHESTRATOR_WORKSPACE_DIR = BASE_DIR / "orchestrator_workspace"

# Ensure all directories exist
for d in [NEEDS_ACTION_DIR, PLANS_DIR, PENDING_APPROVAL_DIR, APPROVED_DIR, DONE_DIR,
          ORCHESTRATOR_WORKSPACE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

file_handler = logging.FileHandler(LOG_DIR / "orchestrator.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(
    open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
)
stream_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[file_handler, stream_handler],
)
logger = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------

_running = True


def _shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received (signal %s). Stopping orchestrator...", signum)
    _running = False


# ---------------------------------------------------------------------------
# LinkedIn daily action quota (like + comment combined, max 5/24h)
# ---------------------------------------------------------------------------

def _load_linkedin_action_quota() -> tuple[int, datetime]:
    """Load the LinkedIn action count and window start from disk."""
    if LINKEDIN_DAILY_ACTIONS_PATH.exists():
        try:
            data = json.loads(LINKEDIN_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
            count = data.get("actions_today", 0)
            window_start = datetime.fromisoformat(
                data.get("window_start_time", datetime.now().isoformat())
            )
            return count, window_start
        except Exception:
            logger.exception("Failed to load LinkedIn action quota; resetting.")
    return 0, datetime.now()


def _save_linkedin_action_quota(count: int, window_start: datetime):
    """Persist the LinkedIn action quota to disk."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    LINKEDIN_DAILY_ACTIONS_PATH.write_text(
        json.dumps({"actions_today": count, "window_start_time": window_start.isoformat()}, indent=2),
        encoding="utf-8",
    )


def _linkedin_actions_remaining() -> int:
    """Return remaining LinkedIn action slots for the current 24h window."""
    count, window_start = _load_linkedin_action_quota()
    # Reset window if 24h has elapsed
    if datetime.now() - window_start >= timedelta(hours=24):
        logger.info("LinkedIn action quota window expired — resetting.")
        _save_linkedin_action_quota(0, datetime.now())
        return LINKEDIN_DAILY_ACTION_LIMIT
    remaining = LINKEDIN_DAILY_ACTION_LIMIT - count
    return max(0, remaining)


def _increment_linkedin_action_count():
    """Record that one LinkedIn like/comment action was executed."""
    count, window_start = _load_linkedin_action_quota()
    # Reset if window has expired
    if datetime.now() - window_start >= timedelta(hours=24):
        count = 0
        window_start = datetime.now()
    count += 1
    _save_linkedin_action_quota(count, window_start)
    logger.info(
        "LinkedIn action quota: %d/%d used in this 24h window.",
        count, LINKEDIN_DAILY_ACTION_LIMIT,
    )


# ---------------------------------------------------------------------------
# X/Twitter daily action quota (reply + like + retweet combined, max 5/24h)
# ---------------------------------------------------------------------------

def _load_x_action_quota() -> tuple[int, datetime]:
    """Load the X action count and window start from disk."""
    if X_DAILY_ACTIONS_PATH.exists():
        try:
            data = json.loads(X_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
            count = data.get("actions_today", 0)
            window_start = datetime.fromisoformat(
                data.get("window_start_time", datetime.now().isoformat())
            )
            return count, window_start
        except Exception:
            logger.exception("Failed to load X action quota; resetting.")
    return 0, datetime.now()


def _save_x_action_quota(count: int, window_start: datetime):
    """Persist the X action quota to disk."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    X_DAILY_ACTIONS_PATH.write_text(
        json.dumps({"actions_today": count, "window_start_time": window_start.isoformat()}, indent=2),
        encoding="utf-8",
    )


def _x_actions_remaining() -> int:
    """Return remaining X action slots for the current 24h window."""
    count, window_start = _load_x_action_quota()
    if datetime.now() - window_start >= timedelta(hours=24):
        logger.info("X action quota window expired — resetting.")
        _save_x_action_quota(0, datetime.now())
        return X_DAILY_ACTION_LIMIT
    remaining = X_DAILY_ACTION_LIMIT - count
    return max(0, remaining)


def _increment_x_action_count():
    """Record that one X reply/like/retweet action batch was executed."""
    count, window_start = _load_x_action_quota()
    if datetime.now() - window_start >= timedelta(hours=24):
        count = 0
        window_start = datetime.now()
    count += 1
    _save_x_action_quota(count, window_start)
    logger.info(
        "X action quota: %d/%d used in this 24h window.",
        count, X_DAILY_ACTION_LIMIT,
    )


# ---------------------------------------------------------------------------
# Instagram daily action quota (DM replies, max 5/24h)
# ---------------------------------------------------------------------------

def _load_instagram_action_quota() -> tuple[int, datetime]:
    if INSTAGRAM_DAILY_ACTIONS_PATH.exists():
        try:
            data = json.loads(INSTAGRAM_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
            count = data.get("actions_today", 0)
            window_start = datetime.fromisoformat(
                data.get("window_start_time", datetime.now().isoformat())
            )
            return count, window_start
        except Exception:
            logger.exception("Failed to load Instagram action quota; resetting.")
    return 0, datetime.now()


def _save_instagram_action_quota(count: int, window_start: datetime):
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    INSTAGRAM_DAILY_ACTIONS_PATH.write_text(
        json.dumps({"actions_today": count, "window_start_time": window_start.isoformat()}, indent=2),
        encoding="utf-8",
    )


def _instagram_actions_remaining() -> int:
    count, window_start = _load_instagram_action_quota()
    if datetime.now() - window_start >= timedelta(hours=24):
        logger.info("Instagram action quota window expired — resetting.")
        _save_instagram_action_quota(0, datetime.now())
        return INSTAGRAM_DAILY_ACTION_LIMIT
    return max(0, INSTAGRAM_DAILY_ACTION_LIMIT - count)


def _increment_instagram_action_count():
    count, window_start = _load_instagram_action_quota()
    if datetime.now() - window_start >= timedelta(hours=24):
        count = 0
        window_start = datetime.now()
    count += 1
    _save_instagram_action_quota(count, window_start)
    logger.info("Instagram action quota: %d/%d used.", count, INSTAGRAM_DAILY_ACTION_LIMIT)


# ---------------------------------------------------------------------------
# Facebook daily action quota (DM replies, max 5/24h)
# ---------------------------------------------------------------------------

def _load_facebook_action_quota() -> tuple[int, datetime]:
    if FACEBOOK_DAILY_ACTIONS_PATH.exists():
        try:
            data = json.loads(FACEBOOK_DAILY_ACTIONS_PATH.read_text(encoding="utf-8"))
            count = data.get("actions_today", 0)
            window_start = datetime.fromisoformat(
                data.get("window_start_time", datetime.now().isoformat())
            )
            return count, window_start
        except Exception:
            logger.exception("Failed to load Facebook action quota; resetting.")
    return 0, datetime.now()


def _save_facebook_action_quota(count: int, window_start: datetime):
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    FACEBOOK_DAILY_ACTIONS_PATH.write_text(
        json.dumps({"actions_today": count, "window_start_time": window_start.isoformat()}, indent=2),
        encoding="utf-8",
    )


def _facebook_actions_remaining() -> int:
    count, window_start = _load_facebook_action_quota()
    if datetime.now() - window_start >= timedelta(hours=24):
        logger.info("Facebook action quota window expired — resetting.")
        _save_facebook_action_quota(0, datetime.now())
        return FACEBOOK_DAILY_ACTION_LIMIT
    return max(0, FACEBOOK_DAILY_ACTION_LIMIT - count)


def _increment_facebook_action_count():
    count, window_start = _load_facebook_action_quota()
    if datetime.now() - window_start >= timedelta(hours=24):
        count = 0
        window_start = datetime.now()
    count += 1
    _save_facebook_action_quota(count, window_start)
    logger.info("Facebook action quota: %d/%d used.", count, FACEBOOK_DAILY_ACTION_LIMIT)


# ---------------------------------------------------------------------------
# Session expiry alerting
# ---------------------------------------------------------------------------

# In-memory consecutive failure counters, keyed by platform name.
# Reset to 0 on any successful action for that platform.
_session_failure_counts: dict[str, int] = {
    "linkedin": 0,
    "x": 0,
    "instagram": 0,
    "facebook": 0,
}

SETUP_COMMANDS = {
    "linkedin":  "python browser/linkedin_setup.py",
    "x":         "python browser/x_setup.py",
    "instagram": "python browser/instagram_setup.py",
    "facebook":  "python browser/facebook_setup.py",
}


def _load_session_alerts_state() -> dict:
    """Load the last-alerted timestamps per platform from disk."""
    if SESSION_ALERTS_STATE_PATH.exists():
        try:
            return json.loads(SESSION_ALERTS_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_session_alerts_state(state: dict):
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_ALERTS_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _session_alert_due(platform: str) -> bool:
    """Return True if enough time has passed since the last alert for this platform."""
    state = _load_session_alerts_state()
    last_str = state.get(platform)
    if not last_str:
        return True
    try:
        last = datetime.fromisoformat(last_str)
        return datetime.now() - last >= timedelta(hours=SESSION_ALERT_COOLDOWN_HOURS)
    except Exception:
        return True


def _record_session_alert_sent(platform: str):
    state = _load_session_alerts_state()
    state[platform] = datetime.now().isoformat()
    _save_session_alerts_state(state)


def _send_session_alert_email(platform: str):
    """Send a Gmail alert email when a platform session appears to have expired.

    Uses the same Claude+MCP subprocess approach as normal email sending.
    Rate-limited by SESSION_ALERT_COOLDOWN_HOURS to avoid inbox flooding.
    """
    if not _session_alert_due(platform):
        logger.debug("Session alert for %s skipped — within cooldown window.", platform)
        return

    setup_cmd = SETUP_COMMANDS.get(platform, f"python browser/{platform}_setup.py")
    subject = f"[AI Employee] {platform.capitalize()} session expired — action required"
    body = (
        f"Your AI Employee system has detected that the {platform.capitalize()} "
        f"browser session has expired.\n\n"
        f"The {platform.capitalize()} watcher has failed to act {SESSION_FAILURE_THRESHOLD} "
        f"times in a row. No new {platform.capitalize()} actions will be executed until "
        f"the session is refreshed.\n\n"
        f"To fix this, run the following command on your server:\n\n"
        f"    {setup_cmd}\n\n"
        f"Then restart the AI Employee system:\n\n"
        f"    pm2 restart ai-employee\n\n"
        f"This alert will not repeat for {SESSION_ALERT_COOLDOWN_HOURS} hours.\n\n"
        f"— AI Employee Orchestrator\n"
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    send_prompt = (
        f"Send a notification email using the mcp__gmail__send_email tool.\n\n"
        f"To: {SESSION_ALERT_EMAIL}\n"
        f"Subject: {subject}\n"
        f"Body (send exactly as written):\n\n{body}\n\n"
        f"RULES:\n"
        f"- Use mcp__gmail__send_email. Do NOT create any files or read anything.\n"
        f"- Send the body exactly as shown above.\n"
    )

    logger.info(
        "Sending session expiry alert for platform '%s' to %s",
        platform, SESSION_ALERT_EMAIL,
    )

    proc = None
    try:
        proc = subprocess.Popen(
            [CLAUDE_CMD, "-p", "--allowedTools", "mcp__gmail__send_email"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ORCHESTRATOR_WORKSPACE_DIR),
        )
        stdout, stderr = proc.communicate(input=send_prompt, timeout=60)
        if proc.returncode == 0:
            logger.info("Session alert email sent for '%s'.", platform)
            _record_session_alert_sent(platform)
        else:
            logger.error(
                "Failed to send session alert for '%s' (exit=%d): %s",
                platform, proc.returncode, stderr[:300],
            )
    except subprocess.TimeoutExpired:
        logger.error("Session alert email timed out for '%s' — killing.", platform)
        if proc:
            _kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        logger.exception("Unexpected error sending session alert for '%s'", platform)


def _record_platform_failure(platform: str):
    """Increment the consecutive failure counter and fire an alert if threshold hit."""
    _session_failure_counts[platform] = _session_failure_counts.get(platform, 0) + 1
    count = _session_failure_counts[platform]
    logger.warning(
        "Platform '%s' consecutive failure count: %d/%d",
        platform, count, SESSION_FAILURE_THRESHOLD,
    )
    if count >= SESSION_FAILURE_THRESHOLD:
        _send_session_alert_email(platform)


def _record_platform_success(platform: str):
    """Reset the consecutive failure counter after a successful action."""
    if _session_failure_counts.get(platform, 0) > 0:
        logger.info("Platform '%s' action succeeded — resetting failure counter.", platform)
    _session_failure_counts[platform] = 0


# ---------------------------------------------------------------------------
# LinkedIn post scheduling (one drafted post per hour)
# ---------------------------------------------------------------------------

def _load_last_linkedin_post_time() -> datetime:
    """Return the datetime of the last LinkedIn post draft, or epoch if never."""
    if LINKEDIN_LAST_POST_PATH.exists():
        try:
            data = json.loads(LINKEDIN_LAST_POST_PATH.read_text(encoding="utf-8"))
            return datetime.fromisoformat(data.get("last_scheduled_at", "1970-01-01T00:00:00"))
        except Exception:
            pass
    return datetime(1970, 1, 1)


def _save_last_linkedin_post_time():
    """Persist the current time as the last LinkedIn post schedule time."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    LINKEDIN_LAST_POST_PATH.write_text(
        json.dumps({"last_scheduled_at": datetime.now().isoformat()}, indent=2),
        encoding="utf-8",
    )


def _schedule_linkedin_post_if_due():
    """Draft a new LinkedIn post for human review if the hourly interval has elapsed."""
    last = _load_last_linkedin_post_time()
    if datetime.now() - last < timedelta(hours=LINKEDIN_POST_INTERVAL_HOURS):
        return  # not yet time

    logger.info(
        "LinkedIn post interval elapsed (%.1fh since last draft) — scheduling new post draft.",
        (datetime.now() - last).total_seconds() / 3600,
    )
    _trigger_claude_linkedin_post_draft()
    _save_last_linkedin_post_time()


# ---------------------------------------------------------------------------
# Facebook post scheduling (one drafted post per FACEBOOK_POST_INTERVAL_HOURS)
# ---------------------------------------------------------------------------

def _load_last_facebook_post_time() -> datetime:
    """Return the datetime of the last Facebook post draft, or epoch if never."""
    if FACEBOOK_LAST_POST_PATH.exists():
        try:
            data = json.loads(FACEBOOK_LAST_POST_PATH.read_text(encoding="utf-8"))
            return datetime.fromisoformat(data.get("last_scheduled_at", "1970-01-01T00:00:00"))
        except Exception:
            pass
    return datetime(1970, 1, 1)


def _save_last_facebook_post_time():
    """Persist the current time as the last Facebook post schedule time."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    FACEBOOK_LAST_POST_PATH.write_text(
        json.dumps({"last_scheduled_at": datetime.now().isoformat()}, indent=2),
        encoding="utf-8",
    )


def _schedule_facebook_post_if_due():
    """Draft a new Facebook post for human review if the interval has elapsed."""
    last = _load_last_facebook_post_time()
    if datetime.now() - last < timedelta(hours=FACEBOOK_POST_INTERVAL_HOURS):
        return  # not yet time

    logger.info(
        "Facebook post interval elapsed (%.1fh since last draft) — scheduling new post draft.",
        (datetime.now() - last).total_seconds() / 3600,
    )
    _trigger_claude_facebook_post_draft()
    _save_last_facebook_post_time()


# ---------------------------------------------------------------------------
# YAML frontmatter parser
# ---------------------------------------------------------------------------

def _parse_frontmatter(filepath: Path) -> dict:
    """Extract YAML frontmatter from a Markdown file (between --- delimiters)."""
    text = filepath.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if match:
        try:
            return yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            logger.exception("Failed to parse frontmatter in %s", filepath)
    return {}


# ---------------------------------------------------------------------------
# Claude Code integration
# ---------------------------------------------------------------------------

def _trigger_claude_reasoning(task_file: Path):
    """
    Invoke Claude Code CLI to reason about an email task file.

    Claude is responsible for:
    - Reading the email task file
    - Drafting a professional reply
    - Creating a plan file in /Plans
    - Creating an approval file in /Pending_Approval that contains:
      the original email, all metadata, AND the drafted reply
    """
    prompt = f"""You are an AI Email Assistant. You must read an email and draft a reply.

STEP 1: Read the email task file at this exact path:
  {task_file}

STEP 2: Create a plan file at this exact path:
  {PLANS_DIR / ('PLAN_' + task_file.name)}

The plan file should contain:
- Summary of the email
- What action is needed (reply, forward, archive, etc.)
- Your reasoning for the drafted reply

STEP 3: Create an approval file at this exact path:
  {PENDING_APPROVAL_DIR / ('REPLY_' + task_file.name)}

The approval file MUST use this EXACT format (including the YAML frontmatter between --- delimiters):

---
type: email_action
action: send_reply
to: "<extract the sender's email address from the email>"
sender_name: "<extract the sender's display name>"
subject: "Re: <original subject>"
in_reply_to: "<the gmail message_id from the email>"
original_date: "<date from the original email>"
status: pending_approval
source_task: "{task_file.name}"
---

# Original Email

**From:** <sender>
**Subject:** <subject>
**Date:** <date>
**Gmail ID:** <message_id>

<paste the full original email content here>

# Proposed Reply

<Write your professional, helpful reply here. This is the ONLY section that will be sent as the email body. Do NOT include greetings like "Dear..." unless appropriate. Write naturally.>

IMPORTANT RULES:
- You MUST create both files (plan + approval) by writing them to disk.
- The "# Proposed Reply" section is what gets sent as the actual email. Write it carefully.
- Do NOT send any email yourself. Only create the files.
- Do NOT modify or delete any existing files.
- Extract the sender email address carefully from the "from" field in the task file.
- If the email doesn't need a reply (e.g. it's a newsletter or notification), still create the plan file explaining why, but skip creating the approval file.
"""

    _invoke_claude_reasoning(task_file, prompt)


def _trigger_claude_tweet_reasoning(task_file: Path):
    """
    Invoke Claude Code CLI to reason about a tweet task file.

    Claude is responsible for:
    - Reading the tweet task file
    - Deciding which actions to take (like, retweet, reply, ignore)
    - Creating a plan file in /Plans
    - Creating an approval file in /Pending_Approval with proposed actions
    """
    prompt = f"""You are an AI Twitter/X Engagement Assistant for @arahmanmoin1, a software engineer
focused on coding, AI, web development, and personal brand building.

STEP 1: Read the tweet task file at this exact path:
  {task_file}

STEP 2: Analyze the tweet and decide which engagement actions are appropriate.
Consider:
- Is this tweet relevant to our brand (coding, AI, web dev, agentic systems)?
- Is the author someone worth engaging with?
- Would replying add value to the conversation?
- Is the tone appropriate for professional engagement?

Possible actions (pick one or more, or "ignore"):
- "like" — Show appreciation (use for relevant, positive tweets)
- "retweet" — Amplify (use sparingly, only for highly relevant content)
- "reply" — Engage in conversation (primary value action)
- "ignore" — Skip engagement (spam, irrelevant, or negative content)

STEP 3: Create a plan file at this exact path:
  {PLANS_DIR / ('PLAN_' + task_file.name)}

The plan file should contain:
- Summary of the tweet
- Why you chose these actions
- Your reasoning for the reply content (if replying)

STEP 4: Create an approval file at this exact path:
  {PENDING_APPROVAL_DIR / ('ACTION_TWEET_' + task_file.name)}

The approval file MUST use this EXACT format:

---
type: tweet_action
actions: ["list", "of", "actions"]
tweet_id: "<tweet_id from the task file>"
author_username: "<author_username from the task file>"
conversation_id: "<conversation_id from the task file>"
source_task: "{task_file.name}"
status: pending_approval
---

# Original Tweet

**Author:** @<username> (<display name>)
**Tweet ID:** <id>
**Type:** <mention/reply/quote_tweet/keyword_match>
**Created:** <timestamp>

<paste the full tweet content here>

# Proposed Actions

## Action 1: <action type>
<For "reply" actions, write the full reply text here. Keep it professional, friendly,
authentic, and concise (under 280 characters). Match the energy of the original tweet.
For "like" or "retweet", just note "Will like/retweet this tweet.">

IMPORTANT RULES:
- You MUST create both files (plan + approval) by writing them to disk.
- For replies, write naturally as @arahmanmoin1. Be helpful, technical when appropriate,
  and genuinely engaged. No corporate-speak.
- Do NOT post any tweets yourself. Only create the files.
- Do NOT modify or delete any existing files.
- If the tweet is spam, irrelevant, or negative, create the plan file explaining why
  you're ignoring it, but skip creating the approval file.
- Keep replies under 280 characters.
"""

    _invoke_claude_reasoning(task_file, prompt)


def _trigger_claude_linkedin_reasoning(task_file: Path):
    """
    Invoke Claude Code CLI to reason about a LinkedIn post task file.

    Claude is responsible for:
    - Reading the LinkedIn post task file
    - Deciding which actions to take (like, comment, ignore)
    - Creating a plan file in /Plans
    - Creating an approval file in /Pending_Approval with proposed actions
    """
    prompt = f"""You are an AI LinkedIn Engagement Assistant for the user with LinkedIn username 'arm-test',
a software engineer focused on coding, AI, web development, and personal brand building.

STEP 1: Read the LinkedIn post task file at this exact path:
  {task_file}

STEP 2: Analyze the post and decide which engagement actions are appropriate.
Consider:
- Is this post relevant to our brand (coding, AI, web dev, agentic systems, tech)?
- Is the author someone worth engaging with professionally?
- Would commenting add genuine value to the conversation?
- Is the tone appropriate for professional engagement on LinkedIn?

Possible actions (pick one or more, or "ignore"):
- "like" — Show appreciation (use for relevant, positive posts)
- "comment" — Engage in conversation (primary value action)
- "ignore" — Skip engagement (spam, irrelevant, or off-topic content)

STEP 3: Create a plan file at this exact path:
  {PLANS_DIR / ('PLAN_' + task_file.name)}

The plan file should contain:
- Summary of the post
- Why you chose these actions
- Your reasoning for the comment content (if commenting)

STEP 4: Create an approval file at this exact path:
  {PENDING_APPROVAL_DIR / ('ACTION_LINKEDIN_' + task_file.name)}

The approval file MUST use this EXACT format:

---
type: linkedin_action
actions: ["list", "of", "actions"]
post_id: "<post_id from the task file>"
post_urn: "<post_urn from the task file>"
author_username: "<author_username from the task file>"
source_task: "{task_file.name}"
status: pending_approval
---

# Original LinkedIn Post

**Author:** <author name> (@<username>)
**Post ID:** <id>
**URN:** <urn>
**Created:** <timestamp>

<paste the full post content here>

# Proposed Actions

## Action 1: <action type>
<For "comment" actions, write the full comment text here. Keep it professional, insightful,
and concise (under 1000 characters). Match the tone of LinkedIn — be genuinely helpful
and add value to the conversation.
For "like", just note "Will like this post.">

IMPORTANT RULES:
- You MUST create both files (plan + approval) by writing them to disk.
- For comments, write naturally and professionally. Be helpful and technically engaged
  where appropriate. No generic platitudes or corporate-speak.
- Do NOT post any content yourself. Only create the files.
- Do NOT modify or delete any existing files.
- If the post is spam, irrelevant, or off-topic, create the plan file explaining why
  you're ignoring it, but skip creating the approval file.
"""

    _invoke_claude_reasoning(task_file, prompt)


def _trigger_claude_odoo_reasoning(task_file: Path):
    """
    Invoke Claude Code CLI to reason about an Odoo event task file.

    Claude is responsible for:
    - Reading the Odoo event file (sale order or invoice change)
    - Assessing urgency and recommending a course of action
    - Creating a plan file in /Plans
    - Creating an approval file in /Pending_Approval with suggested next steps
    """
    prompt = f"""You are an AI Business Operations Assistant monitoring Odoo (ERP system) for the user.

STEP 1: Read the Odoo event task file at this exact path:
  {task_file}

STEP 2: Analyze the event and determine what action or follow-up is recommended.
Consider:
- What changed? (new record, state change, payment status change, overdue?)
- How urgent is this? (overdue invoice > new order > routine state change)
- Is any immediate follow-up required? (send reminder, confirm order, escalate?)
- What is the business impact? (large amount, key customer, blocked workflow?)

STEP 3: Create a plan file at this exact path:
  {PLANS_DIR / ('PLAN_' + task_file.name)}

The plan file should contain:
- What happened and why it matters
- Urgency assessment (high / medium / low)
- Recommended action and reasoning

STEP 4: Create an approval file at this exact path:
  {PENDING_APPROVAL_DIR / ('ACTION_ODOO_' + task_file.name)}

The approval file MUST use this EXACT format:

---
type: odoo_action
odoo_model: "<odoo_model from the task file>"
record_id: "<record_id from the task file>"
record_name: "<record_name from the task file>"
event_type: "<event_type from the task file>"
urgency: "<high|medium|low>"
source_task: "{task_file.name}"
status: pending_approval
---

# Odoo Event: <event_type> — <record_name>

## Summary
<1-2 sentence summary of what happened>

## Urgency: <HIGH / MEDIUM / LOW>
<Brief reason for the urgency level>

## Recommended Actions
<List of specific actions for the human to take in Odoo or externally.
Be concrete and actionable. Example:
- Send payment reminder email to [Customer Name]
- Register payment in Odoo: Accounting > Customers > Invoices > [INV-XXXX] > Register Payment
- Confirm the sales order and schedule delivery
- Escalate to manager: amount exceeds threshold>

## Context
<Any additional context, risks, or notes the human should know>

IMPORTANT RULES:
- You MUST create both files (plan + approval) by writing them to disk.
- Be specific and actionable. Name the exact record, customer, and amounts.
- Do NOT modify Odoo or send any emails yourself. Only create the files.
- Do NOT modify or delete any existing files.
- If the event is routine and requires no action (e.g. minor internal state change),
  create the plan file explaining why, but skip creating the approval file.
"""

    _invoke_claude_reasoning(task_file, prompt)


def _trigger_claude_instagram_reasoning(task_file: Path):
    """
    Invoke Claude Code CLI to reason about an Instagram DM and draft a reply.
    """
    prompt = f"""You are an AI Instagram DM Assistant managing direct messages for the user.

STEP 1: Read the Instagram DM task file at this exact path:
  {task_file}

STEP 2: Analyze the message and decide whether a reply is appropriate.
Consider:
- Is this a genuine message from a real person (not spam/bot)?
- What is the sender asking or saying?
- What tone is appropriate? (friendly, professional, helpful)
- Does this require a response at all?

STEP 3: Create a plan file at this exact path:
  {PLANS_DIR / ('PLAN_' + task_file.name)}

The plan file should contain:
- Summary of the message
- Your reasoning for the reply approach
- Why you chose to reply or ignore

STEP 4: If a reply is appropriate, create an approval file at this exact path:
  {PENDING_APPROVAL_DIR / ('ACTION_INSTAGRAM_' + task_file.name)}

The approval file MUST use this EXACT format:

---
type: instagram_action
action: reply
thread_id: "<thread_id from the task file>"
sender: "<sender from the task file>"
source_task: "{task_file.name}"
status: pending_approval
---

# Instagram DM Reply — <sender>

## Original Message
<paste the full message content here>

## Proposed Reply

## Action 1: Reply
<Write the full reply text here. Keep it natural, conversational, and genuine.
Match the tone of the original message. Be concise — Instagram DMs are casual.
Do NOT use corporate language or generic filler phrases.>

IMPORTANT RULES:
- You MUST create both files (plan + approval) by writing them to disk.
- Write naturally as if you are the account owner.
- Do NOT send any message yourself. Only create the files.
- Do NOT modify or delete any existing files.
- If the message is spam, a bot, or clearly doesn't need a reply, create only
  the plan file explaining why — skip creating the approval file.
"""
    _invoke_claude_reasoning(task_file, prompt)


def _trigger_claude_facebook_reasoning(task_file: Path):
    """
    Invoke Claude Code CLI to reason about a Facebook DM and draft a reply.
    """
    prompt = f"""You are an AI Facebook Messenger Assistant managing direct messages for the user.

STEP 1: Read the Facebook DM task file at this exact path:
  {task_file}

STEP 2: Analyze the message and decide whether a reply is appropriate.
Consider:
- Is this a genuine message from a real person (not spam/bot)?
- What is the sender asking or saying?
- What tone is appropriate? (friendly, professional, helpful)
- Does this require a response at all?

STEP 3: Create a plan file at this exact path:
  {PLANS_DIR / ('PLAN_' + task_file.name)}

The plan file should contain:
- Summary of the message
- Your reasoning for the reply approach
- Why you chose to reply or ignore

STEP 4: If a reply is appropriate, create an approval file at this exact path:
  {PENDING_APPROVAL_DIR / ('ACTION_FACEBOOK_' + task_file.name)}

The approval file MUST use this EXACT format:

---
type: facebook_action
action: reply
thread_id: "<thread_id from the task file>"
sender: "<sender from the task file>"
source_task: "{task_file.name}"
status: pending_approval
---

# Facebook DM Reply — <sender>

## Original Message
<paste the full message content here>

## Proposed Reply

## Action 1: Reply
<Write the full reply text here. Keep it natural, conversational, and genuine.
Match the tone of the original message. Be concise — Messenger DMs are casual.
Do NOT use corporate language or generic filler phrases.>

IMPORTANT RULES:
- You MUST create both files (plan + approval) by writing them to disk.
- Write naturally as if you are the account owner.
- Do NOT send any message yourself. Only create the files.
- Do NOT modify or delete any existing files.
- If the message is spam, a bot, or clearly doesn't need a reply, create only
  the plan file explaining why — skip creating the approval file.
"""
    _invoke_claude_reasoning(task_file, prompt)


def _trigger_claude_facebook_post_draft():
    """Invoke Claude Code CLI to draft an original Facebook post for human review.

    Writes directly to Pending_Approval/ (no Needs_Action task file needed —
    the trigger is time-based, not inbox-based).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    approval_filename = f"ACTION_FACEBOOK_POST_{timestamp}.md"
    approval_path = PENDING_APPROVAL_DIR / approval_filename

    prompt = f"""You are an AI Facebook Content Creator for the user, a software engineer
focused on coding, AI, web development, and agentic systems.

Your task is to draft ONE original Facebook post for human review and approval.
This post will be reviewed before being published — do NOT publish anything yourself.

Create an approval file at this exact path:
  {approval_path}

The approval file MUST use this EXACT format (including the YAML frontmatter):

---
type: facebook_post_action
source_task: "scheduled_post"
status: pending_approval
---

# Proposed Facebook Post

<Write an engaging Facebook post here. The post should:
- Be conversational and relatable — Facebook is more personal than LinkedIn
- Be about a relevant topic: AI, coding, developer life, tech tips, personal stories
- Be 100-250 words
- Share genuine insight, a practical tip, or a short story
- End with a question to encourage comments
- Use short paragraphs — no markdown headers or bullet points
- Feel authentic and personal>

IMPORTANT RULES:
- Create ONLY this one file — nothing else.
- Do NOT read any other files.
- Do NOT post or send anything.
- Write the post content directly after the "# Proposed Facebook Post" heading.
"""

    logger.info("Drafting scheduled Facebook post → %s", approval_filename)
    _invoke_claude_reasoning(approval_path, prompt)


def _trigger_claude_linkedin_post_draft():
    """Invoke Claude Code CLI to draft an original LinkedIn post for human review.

    Writes directly to Pending_Approval/ (no Needs_Action task file needed —
    the trigger is time-based, not inbox-based).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    approval_filename = f"ACTION_LINKEDIN_POST_{timestamp}.md"
    approval_path = PENDING_APPROVAL_DIR / approval_filename

    prompt = f"""You are an AI LinkedIn Content Creator for the user 'arm-test', a software engineer
focused on coding, AI, web development, and agentic systems.

Your task is to draft ONE original LinkedIn post for human review and approval.
This post will be reviewed before being published — do NOT publish anything yourself.

Create an approval file at this exact path:
  {approval_path}

The approval file MUST use this EXACT format (including the YAML frontmatter):

---
type: linkedin_post_action
source_task: "scheduled_post"
status: pending_approval
---

# Proposed LinkedIn Post

<Write a professional, engaging LinkedIn post here. The post should:
- Open with a compelling hook (first line is critical on LinkedIn)
- Be about a relevant tech topic: AI agents, coding, web dev, developer tools,
  agentic systems, Python, productivity, or personal brand building
- Be 150-300 words
- Share genuine insight, a practical tip, or a lesson learned
- End with a question or call to action to encourage engagement
- Use LinkedIn formatting: short paragraphs, line breaks — no markdown headers
- Feel authentic and personal, not corporate or generic>

IMPORTANT RULES:
- Create ONLY this one file — nothing else.
- Do NOT read any other files.
- Do NOT post or send anything.
- Write the post content directly after the "# Proposed LinkedIn Post" heading.
"""

    logger.info("Drafting scheduled LinkedIn post → %s", approval_filename)
    # Re-use _invoke_claude_reasoning with the approval path as the task identifier
    _invoke_claude_reasoning(approval_path, prompt)


def _kill_process_tree(pid: int):
    """Kill a process and all its children on Windows (or POSIX fallback)."""
    try:
        if sys.platform == "win32":
            # taskkill /T kills the entire process tree, /F forces it
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        logger.warning("Failed to kill process tree for PID %d", pid, exc_info=True)


def _invoke_claude_reasoning(task_file: Path, prompt: str):
    """Common Claude Code CLI invocation for reasoning tasks.

    Uses Popen + manual timeout instead of subprocess.run(timeout=) because
    the latter does not reliably kill the process tree on Windows, causing
    the orchestrator to hang indefinitely.
    """

    logger.info("[START] Claude Code reasoning for: %s", task_file.name)
    start_time = time.time()
    timeout_secs = 120

    proc = None
    try:
        proc = subprocess.Popen(
            [CLAUDE_CMD, "-p", "--allowedTools", "Read,Write,Edit"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ORCHESTRATOR_WORKSPACE_DIR),
        )
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout_secs)
        elapsed = int(time.time() - start_time)

        if proc.returncode == 0:
            logger.info(
                "[DONE] Claude Code finished %s in %ds", task_file.name, elapsed
            )
            audit_path = LOG_DIR / f"claude_output_{task_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            audit_path.write_text(stdout or "", encoding="utf-8")
        else:
            logger.error(
                "[FAIL] Claude Code failed for %s (exit=%d, %ds): %s",
                task_file.name,
                proc.returncode,
                elapsed,
                stderr[:500],
            )
    except subprocess.TimeoutExpired:
        elapsed = int(time.time() - start_time)
        logger.error("[TIMEOUT] Claude Code timed out for %s after %ds — killing process tree", task_file.name, elapsed)
        if proc:
            _kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except FileNotFoundError:
        logger.error(
            "Claude Code CLI ('%s') not found on PATH. "
            "Install it or update CLAUDE_CMD.",
            CLAUDE_CMD,
        )


# ---------------------------------------------------------------------------
# Action execution via Gmail MCP (post-approval only)
# ---------------------------------------------------------------------------

def _execute_send_email(approved_file: Path, meta: dict):
    """Send an email by invoking Claude Code with Gmail MCP tools.

    The orchestrator NEVER connects to Gmail directly.
    It delegates sending to Claude Code, which uses the Gmail MCP server.
    """
    to = meta.get("to", "")
    subject = meta.get("subject", "")
    in_reply_to = meta.get("in_reply_to", "")

    if not to or not subject:
        logger.error("Approved email action missing 'to' or 'subject': %s", approved_file)
        return False

    # Extract ONLY the "# Proposed Reply" section — that's what gets sent
    text = approved_file.read_text(encoding="utf-8")
    reply_match = re.search(
        r"#\s*Proposed Reply\s*\n(.*?)(?:\n#|\Z)",
        text,
        re.DOTALL,
    )
    if not reply_match:
        logger.error(
            "No '# Proposed Reply' section found in %s. Cannot send.",
            approved_file,
        )
        return False

    body_plain = reply_match.group(1).strip()
    body_plain = re.sub(r"^#+\s+.*$", "", body_plain, flags=re.MULTILINE).strip()

    # Build prompt for Claude Code to send via Gmail MCP
    send_prompt = f"""You must send an email using the mcp__gmail__send_email tool. This action has been explicitly approved by a human.

Send the email with these EXACT details:
- To: {to}
- Subject: {subject}
- Body (send this EXACTLY as written, do not modify it):

{body_plain}

RULES:
- Use the mcp__gmail__send_email tool to send this email. Do NOT use any other method.
- Send the body EXACTLY as provided above. Do NOT add, remove, or change any text.
- Do NOT create any files. Do NOT read any files. Just send the email.
- After sending, confirm that the email was sent successfully.
"""

    logger.info("Invoking Claude Code + Gmail MCP to send email to %s", to)

    proc = None
    try:
        proc = subprocess.Popen(
            [CLAUDE_CMD, "-p", "--allowedTools", "mcp__gmail__send_email"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ORCHESTRATOR_WORKSPACE_DIR),
        )
        stdout, stderr = proc.communicate(input=send_prompt, timeout=120)

        # Log Claude's output for audit
        audit_path = LOG_DIR / f"mcp_send_{approved_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        audit_path.write_text(
            f"TO: {to}\nSUBJECT: {subject}\nEXIT CODE: {proc.returncode}\n\n"
            f"--- STDOUT ---\n{stdout}\n\n--- STDERR ---\n{stderr}",
            encoding="utf-8",
        )

        if proc.returncode == 0:
            logger.info("Email sent successfully via MCP to %s (subject: %s)", to, subject)
            return True
        else:
            logger.error(
                "Claude Code MCP send failed for %s (exit=%d): %s",
                approved_file.name,
                proc.returncode,
                stderr[:500],
            )
            return False

    except subprocess.TimeoutExpired:
        logger.error("Claude Code MCP send timed out for: %s — killing process tree", approved_file.name)
        if proc:
            _kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return False
    except FileNotFoundError:
        logger.error("Claude Code CLI ('%s') not found on PATH.", CLAUDE_CMD)
        return False


def _execute_tweet_actions(approved_file: Path, meta: dict) -> bool:
    """Execute approved tweet actions via Playwright browser automation.

    Each action (like, retweet, reply) is executed by the browser module.
    Like/retweet failures are logged as warnings (non-critical).
    """
    actions = meta.get("actions", [])
    tweet_id = meta.get("tweet_id", "")
    author_username = meta.get("author_username", "")

    if not tweet_id:
        logger.error("Approved tweet action missing 'tweet_id': %s", approved_file)
        return False

    if not actions:
        logger.warning("No actions listed in %s. Nothing to execute.", approved_file)
        return True

    # Extract reply text from the approval file (look for reply action section)
    reply_text = ""
    if "reply" in actions:
        text = approved_file.read_text(encoding="utf-8")
        reply_match = re.search(
            r"##\s*Action\s*\d+:\s*[Rr]eply\s*\n(.*?)(?:\n##|\n---|\Z)",
            text,
            re.DOTALL,
        )
        if reply_match:
            reply_text = reply_match.group(1).strip()
            reply_text = re.sub(r"^#+\s+.*$", "", reply_text, flags=re.MULTILINE).strip()

        if not reply_text:
            logger.error("Reply action requested but no reply text found in %s", approved_file)
            actions = [a for a in actions if a != "reply"]

    logger.info(
        "Executing tweet actions via browser: %s for tweet %s by @%s",
        actions, tweet_id, author_username,
    )

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            browser_execute_tweet_actions,
            tweet_id=tweet_id,
            author_username=author_username,
            actions=actions,
            reply_text=reply_text,
        )
        try:
            results = future.result(timeout=BROWSER_ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(
                "Browser action timed out after %ds for tweet %s — skipping",
                BROWSER_ACTION_TIMEOUT,
                tweet_id,
            )
            results = {a: False for a in actions}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("Browser action execution failed for tweet %s", tweet_id)
        results = {a: False for a in actions}

    # Write audit log
    audit_path = LOG_DIR / f"browser_tweet_{approved_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    audit_path.write_text(
        f"TWEET_ID: {tweet_id}\nAUTHOR: @{author_username}\n"
        f"ACTIONS: {actions}\nRESULTS: {results}\n",
        encoding="utf-8",
    )

    # Evaluate overall success: like/retweet failures are warnings, reply failure is critical.
    # However, if ALL actions failed (even non-critical ones), treat as platform failure —
    # this catches session-expiry scenarios where only like/retweet was requested.
    overall_success = True
    for action_name, success in results.items():
        if not success:
            if action_name in ("like", "retweet"):
                logger.warning("Non-critical action '%s' failed for tweet %s", action_name, tweet_id)
            else:
                logger.error("Action '%s' failed for tweet %s", action_name, tweet_id)
                overall_success = False

    if results and not any(results.values()):
        logger.error(
            "All actions failed for tweet %s — likely a session or network issue.", tweet_id
        )
        overall_success = False

    return overall_success


def _execute_linkedin_actions(approved_file: Path, meta: dict) -> bool:
    """Execute approved LinkedIn actions via Playwright browser automation.

    Actions supported: like, comment.
    Comment failures are critical; like failures are logged as warnings.
    """
    actions = meta.get("actions", [])
    post_urn = meta.get("post_urn", "")
    post_id = meta.get("post_id", "")
    author_username = meta.get("author_username", "")

    # Resolve URN: if post_urn not set, build from post_id
    if not post_urn and post_id:
        post_urn = f"urn:li:activity:{post_id}"

    if not post_urn:
        logger.error("Approved LinkedIn action missing 'post_urn'/'post_id': %s", approved_file)
        return False

    if not actions:
        logger.warning("No actions listed in %s. Nothing to execute.", approved_file)
        return True

    # Extract comment text from the approval file if commenting
    comment_text = ""
    if "comment" in actions:
        text = approved_file.read_text(encoding="utf-8")
        comment_match = re.search(
            r"##\s*Action\s*\d+:\s*[Cc]omment\s*\n(.*?)(?:\n##|\n---|\Z)",
            text,
            re.DOTALL,
        )
        if comment_match:
            comment_text = comment_match.group(1).strip()
            comment_text = re.sub(r"^#+\s+.*$", "", comment_text, flags=re.MULTILINE).strip()

        if not comment_text:
            logger.error("Comment action requested but no comment text found in %s", approved_file)
            actions = [a for a in actions if a != "comment"]

    logger.info(
        "Executing LinkedIn actions via browser: %s for post %s by @%s",
        actions, post_urn, author_username,
    )

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            browser_execute_linkedin_actions,
            post_urn=post_urn,
            author_username=author_username,
            actions=actions,
            comment_text=comment_text,
        )
        try:
            results = future.result(timeout=BROWSER_ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(
                "Browser action timed out after %ds for LinkedIn post %s — skipping",
                BROWSER_ACTION_TIMEOUT,
                post_urn,
            )
            results = {a: False for a in actions}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("Browser action execution failed for LinkedIn post %s", post_urn)
        results = {a: False for a in actions}

    # Write audit log
    audit_path = LOG_DIR / f"browser_linkedin_{approved_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    audit_path.write_text(
        f"POST_URN: {post_urn}\nAUTHOR: @{author_username}\n"
        f"ACTIONS: {actions}\nRESULTS: {results}\n",
        encoding="utf-8",
    )

    # like failure = warning; comment failure = critical.
    # If ALL actions failed, treat as platform failure regardless (session expiry detection).
    overall_success = True
    for action_name, success in results.items():
        if not success:
            if action_name == "like":
                logger.warning("Non-critical action 'like' failed for LinkedIn post %s", post_urn)
            else:
                logger.error("Action '%s' failed for LinkedIn post %s", action_name, post_urn)
                overall_success = False

    if results and not any(results.values()):
        logger.error(
            "All actions failed for LinkedIn post %s — likely a session or network issue.", post_urn
        )
        overall_success = False

    return overall_success


def _execute_linkedin_post_action(approved_file: Path, meta: dict) -> bool:
    """Post an original LinkedIn post from a human-approved scheduled draft."""
    text = approved_file.read_text(encoding="utf-8")
    post_match = re.search(
        r"#\s*Proposed LinkedIn Post\s*\n(.*?)(?:\n#|\Z)",
        text,
        re.DOTALL,
    )
    if not post_match:
        logger.error("No '# Proposed LinkedIn Post' section found in %s", approved_file)
        return False

    content = post_match.group(1).strip()
    # Strip any markdown headings that Claude may have accidentally added
    content = re.sub(r"^#+\s+.*$", "", content, flags=re.MULTILINE).strip()

    if not content:
        logger.error("Empty post content in %s", approved_file)
        return False

    logger.info("Executing LinkedIn post from %s (%d chars)", approved_file.name, len(content))

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(browser_execute_linkedin_post, content)
        try:
            success = future.result(timeout=BROWSER_ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(
                "LinkedIn post timed out after %ds for %s", BROWSER_ACTION_TIMEOUT, approved_file.name
            )
            success = False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("Error posting LinkedIn content from %s", approved_file.name)
        success = False

    audit_path = LOG_DIR / f"linkedin_post_{approved_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    audit_path.write_text(
        f"FILE: {approved_file.name}\nCONTENT_LEN: {len(content)}\nSUCCESS: {success}\n\n{content}\n",
        encoding="utf-8",
    )

    return success


def _execute_instagram_reply_action(approved_file: Path, meta: dict) -> bool:
    """Send an approved Instagram DM reply via Playwright."""
    thread_id = meta.get("thread_id", "")
    sender = meta.get("sender", "unknown")

    if not thread_id:
        logger.error("Approved Instagram action missing 'thread_id': %s", approved_file)
        return False

    # Extract reply text from the approval file
    text = approved_file.read_text(encoding="utf-8")
    reply_match = re.search(
        r"##\s*Action\s*\d+:\s*[Rr]eply\s*\n(.*?)(?:\n##|\n---|\Z)",
        text,
        re.DOTALL,
    )
    if not reply_match:
        logger.error("No reply text found in %s", approved_file)
        return False

    reply_text = reply_match.group(1).strip()
    reply_text = re.sub(r"^#+\s+.*$", "", reply_text, flags=re.MULTILINE).strip()

    if not reply_text:
        logger.error("Empty reply text in %s", approved_file)
        return False

    logger.info(
        "Executing Instagram reply to @%s thread=%s (%d chars)",
        sender, thread_id, len(reply_text),
    )

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            browser_execute_instagram_reply,
            thread_id=thread_id,
            reply_text=reply_text,
            sender_username=sender,
        )
        try:
            success = future.result(timeout=BROWSER_ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(
                "Instagram reply timed out after %ds for thread %s",
                BROWSER_ACTION_TIMEOUT, thread_id,
            )
            success = False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("Error executing Instagram reply from %s", approved_file.name)
        success = False

    return success


def _execute_facebook_reply_action(approved_file: Path, meta: dict) -> bool:
    """Send an approved Facebook Messenger reply via Playwright."""
    thread_id = meta.get("thread_id", "")
    sender = meta.get("sender", "unknown")

    if not thread_id:
        logger.error("Approved Facebook action missing 'thread_id': %s", approved_file)
        return False

    text = approved_file.read_text(encoding="utf-8")
    reply_match = re.search(
        r"##\s*Action\s*\d+:\s*[Rr]eply\s*\n(.*?)(?:\n##|\n---|\Z)",
        text,
        re.DOTALL,
    )
    if not reply_match:
        logger.error("No reply text found in %s", approved_file)
        return False

    reply_text = reply_match.group(1).strip()
    reply_text = re.sub(r"^#+\s+.*$", "", reply_text, flags=re.MULTILINE).strip()

    if not reply_text:
        logger.error("Empty reply text in %s", approved_file)
        return False

    logger.info(
        "Executing Facebook reply to %s thread=%s (%d chars)",
        sender, thread_id, len(reply_text),
    )

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            browser_execute_facebook_reply,
            thread_id=thread_id,
            reply_text=reply_text,
            sender_name=sender,
        )
        try:
            success = future.result(timeout=BROWSER_ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(
                "Facebook reply timed out after %ds for thread %s",
                BROWSER_ACTION_TIMEOUT, thread_id,
            )
            success = False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("Error executing Facebook reply from %s", approved_file.name)
        success = False

    return success


def _execute_facebook_post_action(approved_file: Path, meta: dict) -> bool:
    """Post an original Facebook wall post from a human-approved draft."""
    text = approved_file.read_text(encoding="utf-8")
    post_match = re.search(
        r"#\s*Proposed Facebook Post\s*\n(.*?)(?:\n#|\Z)",
        text,
        re.DOTALL,
    )
    if not post_match:
        logger.error("No '# Proposed Facebook Post' section found in %s", approved_file)
        return False

    content = post_match.group(1).strip()
    content = re.sub(r"^#+\s+.*$", "", content, flags=re.MULTILINE).strip()

    if not content:
        logger.error("Empty post content in %s", approved_file)
        return False

    logger.info("Executing Facebook post from %s (%d chars)", approved_file.name, len(content))

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(browser_execute_facebook_post, content)
        try:
            success = future.result(timeout=BROWSER_ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(
                "Facebook post timed out after %ds for %s", BROWSER_ACTION_TIMEOUT, approved_file.name
            )
            success = False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("Error posting Facebook content from %s", approved_file.name)
        success = False

    audit_path = LOG_DIR / f"facebook_post_{approved_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    audit_path.write_text(
        f"FILE: {approved_file.name}\nCONTENT_LEN: {len(content)}\nSUCCESS: {success}\n\n{content}\n",
        encoding="utf-8",
    )

    return success


def _execute_approved_action(approved_file: Path):
    """Parse and execute an approved action file, then move it to Done/."""
    meta = _parse_frontmatter(approved_file)
    action = meta.get("action", "")
    action_type = meta.get("type", "")

    logger.info(
        "Executing approved action: type=%s, action=%s, file=%s",
        action_type,
        action,
        approved_file.name,
    )

    success = False

    if action_type == "email_action" and action in ("send_reply", "send_email"):
        success = _execute_send_email(approved_file, meta)
    elif action_type == "tweet_action":
        remaining = _x_actions_remaining()
        if remaining <= 0:
            logger.info(
                "X daily action limit reached (%d/%d) — leaving %s in Approved/ until tomorrow.",
                X_DAILY_ACTION_LIMIT, X_DAILY_ACTION_LIMIT, approved_file.name,
            )
            return  # Leave file in place; do NOT move to Done
        success = _execute_tweet_actions(approved_file, meta)
        if success:
            _increment_x_action_count()
            _record_platform_success("x")
        else:
            _record_platform_failure("x")
    elif action_type == "linkedin_action":
        remaining = _linkedin_actions_remaining()
        if remaining <= 0:
            logger.info(
                "LinkedIn daily action limit reached (%d/%d) — leaving %s in Approved/ until tomorrow.",
                LINKEDIN_DAILY_ACTION_LIMIT, LINKEDIN_DAILY_ACTION_LIMIT, approved_file.name,
            )
            return  # Leave file in place; do NOT move to Done
        success = _execute_linkedin_actions(approved_file, meta)
        if success:
            _increment_linkedin_action_count()
            _record_platform_success("linkedin")
        else:
            _record_platform_failure("linkedin")
    elif action_type == "linkedin_post_action":
        success = _execute_linkedin_post_action(approved_file, meta)
        if success:
            _record_platform_success("linkedin")
        else:
            _record_platform_failure("linkedin")
    elif action_type == "instagram_action":
        remaining = _instagram_actions_remaining()
        if remaining <= 0:
            logger.info(
                "Instagram daily reply limit reached (%d/%d) — leaving %s in Approved/ until tomorrow.",
                INSTAGRAM_DAILY_ACTION_LIMIT, INSTAGRAM_DAILY_ACTION_LIMIT, approved_file.name,
            )
            return
        success = _execute_instagram_reply_action(approved_file, meta)
        if success:
            _increment_instagram_action_count()
            _record_platform_success("instagram")
        else:
            _record_platform_failure("instagram")
    elif action_type == "facebook_action":
        remaining = _facebook_actions_remaining()
        if remaining <= 0:
            logger.info(
                "Facebook daily reply limit reached (%d/%d) — leaving %s in Approved/ until tomorrow.",
                FACEBOOK_DAILY_ACTION_LIMIT, FACEBOOK_DAILY_ACTION_LIMIT, approved_file.name,
            )
            return
        success = _execute_facebook_reply_action(approved_file, meta)
        if success:
            _increment_facebook_action_count()
            _record_platform_success("facebook")
        else:
            _record_platform_failure("facebook")
    elif action_type == "facebook_post_action":
        success = _execute_facebook_post_action(approved_file, meta)
        if success:
            _record_platform_success("facebook")
        else:
            _record_platform_failure("facebook")
    elif action_type == "odoo_action":
        # Observe-only: no automatic execution back into Odoo.
        # The approval file contains Claude's suggested actions for the human to
        # carry out manually in Odoo. Mark as completed and archive.
        logger.info(
            "Odoo action acknowledged (observe-only mode) — archiving %s",
            approved_file.name,
        )
        success = True
    else:
        logger.warning(
            "Unknown action type '%s/%s' in %s. Moving to Done/ as unhandled.",
            action_type,
            action,
            approved_file.name,
        )
        success = True  # Move it along so it doesn't block the queue

    # Move to Done/ with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    status = "completed" if success else "failed"
    dest = DONE_DIR / f"{status}_{timestamp}_{approved_file.name}"
    shutil.move(str(approved_file), str(dest))
    logger.info("Moved %s → %s", approved_file.name, dest.name)

    # Clean up the corresponding plan file and move original task to Done
    source_task = meta.get("source_task", "")
    if source_task:
        plan_file = PLANS_DIR / f"PLAN_{source_task}"
        if plan_file.exists():
            plan_file.unlink()
            logger.info("Removed plan file: %s", plan_file.name)

        task_file = NEEDS_ACTION_DIR / source_task
        if task_file.exists():
            task_dest = DONE_DIR / f"processed_{timestamp}_{source_task}"
            shutil.move(str(task_file), str(task_dest))
            logger.info("Moved original task %s → Done/", source_task)


# ---------------------------------------------------------------------------
# Task priority ordering: gmail → linkedin → x → instagram → odoo
# ---------------------------------------------------------------------------

def _task_priority(filename: str) -> int:
    """Return a sort key so tasks are processed in the configured priority order."""
    if filename.startswith(("EMAIL_", "REPLY_")):
        return 1
    elif filename.startswith("LINKEDIN_POST_"):
        return 2
    elif filename.startswith("TWEET_"):
        return 3
    elif filename.startswith("INSTAGRAM_DM_"):
        return 4
    elif filename.startswith("FACEBOOK_DM_"):
        return 5
    elif filename.startswith("ODOO_"):
        return 6
    else:
        return 7  # unknown types processed last


def _approved_priority(filename: str) -> int:
    """Return a sort key for Approved/ files matching the same priority order."""
    if filename.startswith("REPLY_"):
        return 1
    elif filename.startswith("ACTION_LINKEDIN_"):
        return 2
    elif filename.startswith("ACTION_TWEET_"):
        return 3
    elif filename.startswith("ACTION_INSTAGRAM_"):
        return 4
    elif filename.startswith("ACTION_FACEBOOK_"):
        return 5
    elif filename.startswith("ACTION_ODOO_"):
        return 6
    else:
        return 7


# ---------------------------------------------------------------------------
# Folder monitors
# ---------------------------------------------------------------------------

def _scan_needs_action():
    """Process files in Needs_Action/ up to MAX_REASONING_PER_CYCLE per cycle.

    Processes a limited batch per cycle so that _scan_approved() gets a chance
    to run between batches. Remaining tasks are picked up in the next cycle.
    Deduplication is handled by checking if an approval file already exists
    (in Pending_Approval/ or Approved/) — no separate state tracking needed.

    - Promo/newsletter emails (no reply needed) → moved to Done/ immediately.
    - Reply-worthy emails → stay in Needs_Action/ and Plans/ until approval cycle completes."""
    current_files = sorted(
        (f.name for f in NEEDS_ACTION_DIR.iterdir() if f.is_file()),
        key=_task_priority,
    )

    if not current_files:
        return

    total = len(current_files)
    reasoning_count = 0

    for idx, filename in enumerate(current_files, 1):
        if not _running:
            break

        # Yield to approved-action processing after MAX_REASONING_PER_CYCLE Claude calls
        if reasoning_count >= MAX_REASONING_PER_CYCLE:
            logger.info(
                "Processed %d reasoning tasks this cycle — yielding to check Approved/ (%d tasks remaining)",
                reasoning_count,
                total - idx + 1,
            )
            break

        filepath = NEEDS_ACTION_DIR / filename

        # Determine task type from frontmatter or filename prefix
        meta = _parse_frontmatter(filepath)
        task_type = meta.get("type", "email")  # default to email for backwards compat

        # Determine approval file prefix based on task type
        if task_type in ("tweet", "watchlist"):
            approval_prefix = "ACTION_TWEET_"
        elif task_type == "linkedin_post":
            approval_prefix = "ACTION_LINKEDIN_"
        elif task_type == "odoo_event":
            approval_prefix = "ACTION_ODOO_"
        elif task_type == "instagram_dm":
            approval_prefix = "ACTION_INSTAGRAM_"
        elif task_type == "facebook_dm":
            approval_prefix = "ACTION_FACEBOOK_"
        else:
            approval_prefix = "REPLY_"

        approval_name = f"{approval_prefix}{filename}"

        # Skip files that already have a pending or approved action (e.g. after restart)
        if (PENDING_APPROVAL_DIR / approval_name).exists() or (APPROVED_DIR / approval_name).exists():
            continue

        # Check for an orphaned plan: plan exists but no approval is in-flight.
        # This happens when:
        #   - Claude created a plan but decided no action was needed (and the task
        #     wasn't moved to Done/ due to a crash/restart mid-cycle), OR
        #   - The approval was rejected/deleted by the human without cleaning up
        #     the plan and task files.
        # Fix: delete the orphaned plan so the task gets re-reasoned this cycle.
        plan_name = f"PLAN_{filename}"
        if (PLANS_DIR / plan_name).exists():
            logger.info(
                "Orphaned plan detected for %s (plan exists but no approval in-flight) "
                "— deleting plan and re-processing.",
                filename,
            )
            try:
                (PLANS_DIR / plan_name).unlink()
            except Exception:
                logger.warning("Could not delete orphaned plan %s", plan_name, exc_info=True)

        logger.info("[%d/%d] Processing %s task: %s", idx, total, task_type, filename)

        try:
            if task_type in ("tweet", "watchlist"):
                _trigger_claude_tweet_reasoning(filepath)
            elif task_type == "linkedin_post":
                _trigger_claude_linkedin_reasoning(filepath)
            elif task_type == "odoo_event":
                _trigger_claude_odoo_reasoning(filepath)
            elif task_type == "instagram_dm":
                _trigger_claude_instagram_reasoning(filepath)
            elif task_type == "facebook_dm":
                _trigger_claude_facebook_reasoning(filepath)
            else:
                _trigger_claude_reasoning(filepath)
        except Exception:
            logger.exception("[%d/%d] ERROR processing %s, skipping", idx, total, filename)

        reasoning_count += 1

        # Check if an approval file was created
        approval_file = PENDING_APPROVAL_DIR / approval_name
        if approval_file.exists():
            # Needs human approval: keep task and plan in place
            logger.info("[%d/%d] Approval file created — %s stays until approved", idx, total, filename)
        else:
            # No action needed (spam/irrelevant): move to Done/ immediately
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = DONE_DIR / f"processed_{timestamp}_{filename}"
            if filepath.exists():
                shutil.move(str(filepath), str(dest))
                logger.info("[%d/%d] Moved %s → Done/ (no action needed)", idx, total, filename)

            # Clean up the corresponding plan file
            plan_file = PLANS_DIR / plan_name
            if plan_file.exists():
                plan_file.unlink()
                logger.info("[%d/%d] Removed plan file: %s", idx, total, plan_file.name)


def _scan_approved():
    """Execute all files currently in Approved/.

    We process every file present each cycle rather than tracking "new" files.
    Processed files are moved to Done/ so they naturally disappear from Approved/
    and won't be double-processed. This is simpler and avoids the race condition
    where two orchestrator instances update _known_approved simultaneously,
    causing files to be silently skipped.
    """
    current_files = sorted(
        (f.name for f in APPROVED_DIR.iterdir() if f.is_file()),
        key=_approved_priority,
    )
    for filename in current_files:
        filepath = APPROVED_DIR / filename
        if not filepath.exists():
            continue  # already processed (e.g. by a concurrent instance)
        logger.info("Approved action detected: %s", filename)
        _execute_approved_action(filepath)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    global _running

    # Singleton guard — prevent two orchestrator instances competing for files
    lock_path = BASE_DIR / "orchestrator.lock"
    lock_file = None
    try:
        if lock_path.exists():
            old_pid = int(lock_path.read_text().strip())
            try:
                os.kill(old_pid, 0)
                logger.error(
                    "Another orchestrator instance already running (PID %d). Exiting.", old_pid
                )
                sys.exit(1)
            except (OSError, ProcessLookupError):
                pass  # stale lock
        lock_path.write_text(str(os.getpid()))
        lock_file = lock_path
    except Exception:
        logger.warning("Could not acquire orchestrator lockfile — proceeding anyway", exc_info=True)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("=" * 60)
    logger.info("orchestrator.py starting — System Coordinator")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Poll interval: %ds", POLL_INTERVAL)
    logger.info("=" * 60)

    needs_count = len([f for f in NEEDS_ACTION_DIR.iterdir() if f.is_file()])
    approved_count = len([f for f in APPROVED_DIR.iterdir() if f.is_file()])
    logger.info(
        "Initial state: %d file(s) in Needs_Action, %d in Approved",
        needs_count,
        approved_count,
    )

    while _running:
        try:
            _scan_needs_action()
            _scan_approved()
            _schedule_linkedin_post_if_due()
            _schedule_facebook_post_if_due()
        except Exception:
            logger.exception("Error during orchestration cycle")

        for _ in range(POLL_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    if lock_file and lock_file.exists():
        try:
            lock_file.unlink()
        except Exception:
            pass

    logger.info("orchestrator.py exited cleanly.")


if __name__ == "__main__":
    main()
