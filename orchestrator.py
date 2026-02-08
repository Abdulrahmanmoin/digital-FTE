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
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from browser.x_actions import execute_tweet_actions as browser_execute_tweet_actions

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
BROWSER_ACTION_TIMEOUT = 90  # seconds before killing a hung browser action
CLAUDE_CMD = "claude"  # Claude Code CLI command

# Ensure all directories exist
for d in [NEEDS_ACTION_DIR, PLANS_DIR, PENDING_APPROVAL_DIR, APPROVED_DIR, DONE_DIR]:
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
_known_approved: set[str] = set()


def _shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received (signal %s). Stopping orchestrator...", signum)
    _running = False


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
            cwd=str(BASE_DIR),
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
            cwd=str(BASE_DIR),
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

    # Evaluate overall success: like/retweet failures are warnings, reply failure is critical
    overall_success = True
    for action_name, success in results.items():
        if not success:
            if action_name in ("like", "retweet"):
                logger.warning("Non-critical action '%s' failed for tweet %s", action_name, tweet_id)
            else:
                logger.error("Action '%s' failed for tweet %s", action_name, tweet_id)
                overall_success = False

    return overall_success


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
        success = _execute_tweet_actions(approved_file, meta)
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
    current_files = sorted(f.name for f in NEEDS_ACTION_DIR.iterdir() if f.is_file())

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
        if task_type == "tweet":
            approval_prefix = "ACTION_TWEET_"
        else:
            approval_prefix = "REPLY_"

        approval_name = f"{approval_prefix}{filename}"

        # Skip files that already have a pending or approved action (e.g. after restart)
        if (PENDING_APPROVAL_DIR / approval_name).exists() or (APPROVED_DIR / approval_name).exists():
            continue

        # Also check if already moved to Done/ (plan exists = already processed)
        plan_name = f"PLAN_{filename}"
        if (PLANS_DIR / plan_name).exists():
            continue

        logger.info("[%d/%d] Processing %s task: %s", idx, total, task_type, filename)

        try:
            if task_type == "tweet":
                _trigger_claude_tweet_reasoning(filepath)
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
    """Detect new files in Approved/ and execute the approved actions."""
    global _known_approved
    current_files = {f.name for f in APPROVED_DIR.iterdir() if f.is_file()}
    new_files = current_files - _known_approved

    for filename in sorted(new_files):
        filepath = APPROVED_DIR / filename
        logger.info("Approved action detected: %s", filename)
        _execute_approved_action(filepath)

    # Re-read after execution (files get moved to Done/)
    _known_approved = {f.name for f in APPROVED_DIR.iterdir() if f.is_file()}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    global _running

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("=" * 60)
    logger.info("orchestrator.py starting — System Coordinator")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Poll interval: %ds", POLL_INTERVAL)
    logger.info("=" * 60)

    # Start with empty approved set — process ALL approved files on startup
    global _known_approved
    _known_approved = set()

    needs_count = len([f for f in NEEDS_ACTION_DIR.iterdir() if f.is_file()])
    approved_count = len([f for f in APPROVED_DIR.iterdir() if f.is_file()])
    logger.info(
        "Initial state: %d file(s) in Needs_Action, %d in Approved — will process all",
        needs_count,
        approved_count,
    )

    while _running:
        try:
            _scan_needs_action()
            _scan_approved()
        except Exception:
            logger.exception("Error during orchestration cycle")

        for _ in range(POLL_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    logger.info("orchestrator.py exited cleanly.")


if __name__ == "__main__":
    main()
