"""
odoo_watcher.py - Odoo Sense Component (XML-RPC Polling)

Responsibility:
- Connects to Odoo via the built-in XML-RPC API
- Polls Sales Orders and Invoices/Bills every CHECK_INTERVAL seconds
- Detects new records and state changes (e.g. quotation confirmed, invoice paid)
- Creates a structured Markdown file in AI_Employee_Vault/Needs_Action/ for
  each detected event, containing full context for Claude to reason on
- Tracks last-known state of each record to avoid duplicate events
- Persists processed state to disk so restarts don't re-fire old events

Boundary:
- READ-ONLY access to Odoo — does NOT create, update, or delete records
- Does NOT reason, plan, approve, or execute actions
- Does NOT trigger the orchestrator directly; communication is file-based only

Assumptions:
- Credentials at credentials/odoo_config.json (url, database, username, api_key)
  Get your API key: Odoo → Settings → Users → Your Profile → API Keys
- The Odoo instance must have xmlrpc enabled (it is by default)
- Python's built-in xmlrpc.client is used — no extra pip installs needed
"""

import json
import logging
import re
import sys
import xmlrpc.client
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from base_watcher import BaseWatcher

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
CREDENTIALS_DIR = BASE_DIR / "credentials"
CONFIG_PATH = CREDENTIALS_DIR / "odoo_config.json"
STATE_PATH = CREDENTIALS_DIR / ".odoo_state.json"      # last-known state per record
LAST_POLL_PATH = CREDENTIALS_DIR / ".odoo_last_poll.json"

CHECK_INTERVAL = 600    # seconds between polls (10 minutes — lower priority)
LOOKBACK_MINUTES = 30   # on startup, look back this many minutes to catch recent changes

# Sale order state human labels
SALE_STATE_LABELS = {
    "draft": "Quotation",
    "sent": "Quotation Sent",
    "sale": "Sales Order Confirmed",
    "done": "Locked",
    "cancel": "Cancelled",
}

# Invoice/Bill state labels
INV_STATE_LABELS = {
    "draft": "Draft",
    "posted": "Posted (Confirmed)",
    "cancel": "Cancelled",
}

INV_PAYMENT_LABELS = {
    "not_paid": "Not Paid",
    "in_payment": "Payment Registered",
    "paid": "Fully Paid",
    "partial": "Partially Paid",
    "reversed": "Reversed",
}

INV_TYPE_LABELS = {
    "out_invoice": "Customer Invoice",
    "out_refund": "Customer Credit Note",
    "in_invoice": "Vendor Bill",
    "in_refund": "Vendor Credit Note",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "odoo_watcher.log", encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("odoo_watcher")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_filename(text: str, max_len: int = 40) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]', '_', str(text))
    return text.strip("_")[:max_len]


def _get_name(field_value) -> str:
    """Odoo many2one fields return [id, 'Name'] or False."""
    if isinstance(field_value, list) and len(field_value) == 2:
        return str(field_value[1])
    if field_value is False or field_value is None:
        return "—"
    return str(field_value)


# ---------------------------------------------------------------------------
# OdooWatcher
# ---------------------------------------------------------------------------

class OdooWatcher(BaseWatcher):
    def __init__(self):
        super().__init__(vault_path=str(VAULT_PATH), check_interval=CHECK_INTERVAL)

        self._uid: int | None = None
        self._models = None
        self._db: str = ""
        self._api_key: str = ""
        self._connected = False

        self._state: dict = {}       # {"{model}:{id}": {state, payment_state, write_date}}
        self._last_poll: datetime | None = None

        self._load_config_and_connect()
        self._load_state()
        self._load_last_poll()

    # -- Connection ----------------------------------------------------------

    def _load_config_and_connect(self):
        if not CONFIG_PATH.exists():
            logger.error(
                "Odoo config not found at %s. "
                "Copy credentials/odoo_config.json and fill in your URL, database, "
                "username, and API key.",
                CONFIG_PATH,
            )
            return

        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            url = cfg["url"].rstrip("/")
            self._db = cfg["database"]
            username = cfg["username"]
            # Accept either 'password' or legacy 'api_key' field
            self._api_key = cfg.get("password") or cfg.get("api_key", "")

            if not self._api_key or "your-" in self._api_key:
                logger.error(
                    "odoo_config.json is missing a password. "
                    "Set the 'password' field to your Odoo login password."
                )
                return

            logger.info("Connecting to Odoo at %s (db=%s, user=%s) ...", url, self._db, username)
            common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
            self._uid = common.authenticate(self._db, username, self._api_key, {})

            if not self._uid:
                logger.error(
                    "Odoo authentication failed for user '%s'. "
                    "Check credentials/odoo_config.json.",
                    username,
                )
                return

            self._models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
            self._connected = True
            logger.info(
                "Connected to Odoo at %s (db=%s, uid=%d)",
                url, self._db, self._uid,
            )

        except Exception:
            logger.exception("Failed to connect to Odoo")

    def _execute(self, model: str, method: str, domain: list, kwargs: dict) -> list:
        """Thin wrapper around models.execute_kw with error handling."""
        return self._models.execute_kw(
            self._db, self._uid, self._api_key,
            model, method, [domain], kwargs,
        )

    # -- State persistence ---------------------------------------------------

    def _load_state(self):
        if STATE_PATH.exists():
            try:
                self._state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                logger.info("Loaded state for %d Odoo records.", len(self._state))
            except Exception:
                logger.exception("Failed to load Odoo state; starting fresh.")
                self._state = {}

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _load_last_poll(self):
        if LAST_POLL_PATH.exists():
            try:
                data = json.loads(LAST_POLL_PATH.read_text(encoding="utf-8"))
                self._last_poll = datetime.fromisoformat(data["last_poll"])
                logger.info("Last poll time: %s", self._last_poll.isoformat())
            except Exception:
                self._last_poll = None
        if self._last_poll is None:
            self._last_poll = datetime.now() - timedelta(minutes=LOOKBACK_MINUTES)
            logger.info(
                "No last poll time found — starting lookback from %s",
                self._last_poll.isoformat(),
            )

    def _save_last_poll(self, poll_time: datetime):
        LAST_POLL_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_POLL_PATH.write_text(
            json.dumps({"last_poll": poll_time.isoformat()}),
            encoding="utf-8",
        )

    # -- Odoo polling --------------------------------------------------------

    def _model_exists(self, model: str) -> bool:
        """Check if a model is installed in this Odoo instance."""
        try:
            result = self._execute(
                "ir.model", "search_read",
                [["model", "=", model]],
                {"fields": ["model"], "limit": 1},
            )
            return bool(result)
        except Exception:
            return False

    def _fetch_sale_orders(self, since: str) -> list[dict]:
        """Fetch sale orders modified since `since` (Odoo datetime string)."""
        if not self._model_exists("sale.order"):
            logger.debug("sale.order model not installed — skipping. Install the Sales app in Odoo.")
            return []
        try:
            records = self._execute(
                "sale.order", "search_read",
                [["write_date", ">=", since]],
                {
                    "fields": [
                        "id", "name", "state", "partner_id", "amount_total",
                        "date_order", "write_date", "user_id", "origin", "note",
                        "invoice_status",
                    ],
                    "limit": 50,
                    "order": "write_date asc",
                },
            )
            return records
        except Exception:
            logger.exception("Error fetching sale orders from Odoo")
            return []

    def _fetch_invoices(self, since: str) -> list[dict]:
        """Fetch invoices/bills modified since `since`."""
        if not self._model_exists("account.move"):
            logger.debug("account.move model not installed — skipping. Install the Invoicing app in Odoo.")
            return []
        try:
            records = self._execute(
                "account.move", "search_read",
                [
                    ["write_date", ">=", since],
                    ["move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]],
                ],
                {
                    "fields": [
                        "id", "name", "move_type", "state", "payment_state",
                        "partner_id", "amount_total", "amount_residual",
                        "invoice_date", "invoice_date_due", "write_date",
                        "invoice_user_id", "invoice_origin", "narration",
                    ],
                    "limit": 50,
                    "order": "write_date asc",
                },
            )
            return records
        except Exception:
            logger.exception("Error fetching invoices from Odoo")
            return []

    def _detect_sale_order_events(self, records: list[dict]) -> list[dict]:
        """Compare sale orders against stored state, return list of event dicts."""
        events = []
        for rec in records:
            key = f"sale.order:{rec['id']}"
            prev = self._state.get(key)
            curr_state = rec.get("state", "")

            if prev is None:
                # New record
                event_type = {
                    "draft": "new_quotation",
                    "sent": "new_quotation_sent",
                    "sale": "new_order_confirmed",
                    "done": "new_order_locked",
                    "cancel": "new_order_cancelled",
                }.get(curr_state, "new_sale_order")
                events.append({"model": "sale.order", "event_type": event_type, "record": rec, "prev": None})
            else:
                prev_state = prev.get("state", "")
                if curr_state != prev_state:
                    event_type = {
                        ("draft", "sent"): "quotation_sent",
                        ("draft", "sale"): "order_confirmed",
                        ("sent", "sale"): "order_confirmed",
                        ("sale", "done"): "order_locked",
                        ("draft", "cancel"): "quotation_cancelled",
                        ("sent", "cancel"): "quotation_cancelled",
                        ("sale", "cancel"): "order_cancelled",
                    }.get((prev_state, curr_state), "state_changed")
                    events.append({"model": "sale.order", "event_type": event_type, "record": rec, "prev": prev})

            # Update stored state
            self._state[key] = {
                "state": curr_state,
                "write_date": rec.get("write_date", ""),
            }

        return events

    def _detect_invoice_events(self, records: list[dict]) -> list[dict]:
        """Compare invoices against stored state, return list of event dicts."""
        events = []
        today = datetime.now().date()

        for rec in records:
            key = f"account.move:{rec['id']}"
            prev = self._state.get(key)
            curr_state = rec.get("state", "")
            curr_payment = rec.get("payment_state", "")

            if prev is None:
                event_type = {
                    "draft": "new_draft_invoice",
                    "posted": "new_invoice_posted",
                    "cancel": "new_invoice_cancelled",
                }.get(curr_state, "new_invoice")

                # Check for overdue on new posted invoices
                if curr_state == "posted" and curr_payment in ("not_paid", "partial"):
                    due_str = rec.get("invoice_date_due")
                    if due_str:
                        try:
                            due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
                            if due_date < today:
                                event_type = "invoice_overdue"
                        except ValueError:
                            pass

                events.append({"model": "account.move", "event_type": event_type, "record": rec, "prev": None})

            else:
                prev_state = prev.get("state", "")
                prev_payment = prev.get("payment_state", "")
                changed = False

                if curr_state != prev_state:
                    event_type = {
                        ("draft", "posted"): "invoice_posted",
                        ("posted", "cancel"): "invoice_cancelled",
                        ("draft", "cancel"): "invoice_cancelled",
                    }.get((prev_state, curr_state), "invoice_state_changed")
                    events.append({"model": "account.move", "event_type": event_type, "record": rec, "prev": prev})
                    changed = True

                if not changed and curr_payment != prev_payment:
                    event_type = {
                        "paid": "invoice_fully_paid",
                        "in_payment": "invoice_payment_registered",
                        "partial": "invoice_partially_paid",
                        "reversed": "invoice_reversed",
                    }.get(curr_payment, "invoice_payment_changed")
                    events.append({"model": "account.move", "event_type": event_type, "record": rec, "prev": prev})

                # Overdue check (runs every poll, only fires once per record per day)
                if not changed and curr_state == "posted" and curr_payment in ("not_paid", "partial"):
                    due_str = rec.get("invoice_date_due")
                    if due_str:
                        try:
                            due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
                            last_overdue = prev.get("last_overdue_alert", "")
                            if due_date < today and last_overdue != str(today):
                                events.append({
                                    "model": "account.move",
                                    "event_type": "invoice_overdue",
                                    "record": rec,
                                    "prev": prev,
                                })
                                self._state[key]["last_overdue_alert"] = str(today)
                        except ValueError:
                            pass

            # Update stored state
            self._state[key] = {
                **self._state.get(key, {}),
                "state": curr_state,
                "payment_state": curr_payment,
                "write_date": rec.get("write_date", ""),
            }

        return events

    # -- BaseWatcher interface -----------------------------------------------

    def check_for_updates(self) -> list:
        """Poll Odoo for changes to sales orders and invoices."""
        if not self._connected:
            logger.warning("Odoo not connected — skipping poll.")
            return []

        poll_start = datetime.now()
        # Odoo datetime format: "YYYY-MM-DD HH:MM:SS"
        since = self._last_poll.strftime("%Y-%m-%d %H:%M:%S")

        logger.info("Polling Odoo for changes since %s ...", since)

        sale_records = self._fetch_sale_orders(since)
        inv_records = self._fetch_invoices(since)

        logger.info(
            "Fetched %d sale order(s) and %d invoice(s) modified since last poll.",
            len(sale_records), len(inv_records),
        )

        events = []
        events.extend(self._detect_sale_order_events(sale_records))
        events.extend(self._detect_invoice_events(inv_records))

        self._save_state()
        self._save_last_poll(poll_start)
        self._last_poll = poll_start

        if events:
            logger.info("Detected %d Odoo event(s) to action.", len(events))
        else:
            logger.debug("No new Odoo events this cycle.")

        return events

    def create_action_file(self, event: dict) -> Path:
        """Write a Markdown file to Needs_Action/ describing the Odoo event."""
        model = event["model"]
        event_type = event["event_type"]
        rec = event["record"]
        prev = event.get("prev")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if model == "sale.order":
            return self._write_sale_order_file(rec, event_type, prev, timestamp)
        elif model == "account.move":
            return self._write_invoice_file(rec, event_type, prev, timestamp)
        else:
            logger.warning("Unknown model in event: %s", model)
            return None

    def _write_sale_order_file(self, rec: dict, event_type: str, prev: dict | None, timestamp: str) -> Path:
        rec_name = _sanitize_filename(rec.get("name", str(rec["id"])))
        filename = f"ODOO_SALE_{timestamp}_{event_type}_{rec_name}.md"

        state = rec.get("state", "")
        state_label = SALE_STATE_LABELS.get(state, state)
        prev_state_label = SALE_STATE_LABELS.get(prev.get("state", ""), "") if prev else ""
        partner = _get_name(rec.get("partner_id"))
        assigned_to = _get_name(rec.get("user_id"))
        amount = rec.get("amount_total", 0)
        date_order = rec.get("date_order", "")
        origin = rec.get("origin") or "—"

        change_summary = (
            f"State changed: **{prev_state_label}** → **{state_label}**"
            if prev else f"New record detected with state: **{state_label}**"
        )

        content = f"""---
type: odoo_event
subtype: sale_order
odoo_model: sale.order
record_id: "{rec['id']}"
record_name: "{rec.get('name', '')}"
event_type: "{event_type}"
current_state: "{state}"
partner: "{partner}"
amount_total: {amount}
received_at: "{datetime.now().isoformat()}"
status: pending
---

# Odoo: Sale Order Event — {rec.get('name', rec['id'])}

## Event
**Type:** `{event_type}`
{change_summary}

## Order Details
| Field         | Value |
|---------------|-------|
| Order Number  | {rec.get('name', '—')} |
| Customer      | {partner} |
| Amount        | {amount:,.2f} |
| Status        | {state_label} |
| Assigned To   | {assigned_to} |
| Order Date    | {date_order} |
| Source/Origin | {origin} |
| Invoice Status | {rec.get('invoice_status', '—')} |

## Notes / Internal Comment
{rec.get('note') or '_(none)_'}

## Previous State
{f'Was: **{prev_state_label}** (`{prev.get("state", "")}`)' if prev else '_No previous state — newly detected record._'}

## Suggested Actions
Consider what response (if any) is appropriate. Examples:
- Follow up with customer if quotation has not been confirmed
- Send order confirmation / proforma invoice
- Check if delivery has been scheduled
- Flag for internal review

## Raw Reference
- Odoo Model: `sale.order`
- Record ID: `{rec['id']}`
- Write Date: `{rec.get('write_date', '')}`
"""
        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info("Created: %s", filename)
        return filepath

    def _write_invoice_file(self, rec: dict, event_type: str, prev: dict | None, timestamp: str) -> Path:
        rec_name = _sanitize_filename(rec.get("name", str(rec["id"])))
        filename = f"ODOO_INV_{timestamp}_{event_type}_{rec_name}.md"

        move_type = rec.get("move_type", "")
        state = rec.get("state", "")
        payment_state = rec.get("payment_state", "")
        state_label = INV_STATE_LABELS.get(state, state)
        payment_label = INV_PAYMENT_LABELS.get(payment_state, payment_state)
        type_label = INV_TYPE_LABELS.get(move_type, move_type)
        partner = _get_name(rec.get("partner_id"))
        assigned_to = _get_name(rec.get("invoice_user_id"))
        amount_total = rec.get("amount_total", 0)
        amount_due = rec.get("amount_residual", 0)
        inv_date = rec.get("invoice_date", "—")
        due_date = rec.get("invoice_date_due", "—")
        origin = rec.get("invoice_origin") or "—"

        # Build change summary
        if prev:
            prev_state = INV_STATE_LABELS.get(prev.get("state", ""), prev.get("state", ""))
            prev_pay = INV_PAYMENT_LABELS.get(prev.get("payment_state", ""), prev.get("payment_state", ""))
            change_summary = f"State: **{prev_state}** → **{state_label}**  |  Payment: **{prev_pay}** → **{payment_label}**"
        else:
            change_summary = f"New record detected — State: **{state_label}**, Payment: **{payment_label}**"

        overdue_note = ""
        if event_type == "invoice_overdue":
            overdue_note = f"\n> ⚠️ **OVERDUE** — Due date was `{due_date}`. Amount outstanding: {amount_due:,.2f}\n"

        content = f"""---
type: odoo_event
subtype: invoice
odoo_model: account.move
record_id: "{rec['id']}"
record_name: "{rec.get('name', '')}"
event_type: "{event_type}"
move_type: "{move_type}"
current_state: "{state}"
payment_state: "{payment_state}"
partner: "{partner}"
amount_total: {amount_total}
amount_due: {amount_due}
invoice_date_due: "{due_date}"
received_at: "{datetime.now().isoformat()}"
status: pending
---

# Odoo: Invoice Event — {rec.get('name', rec['id'])}

## Event
**Type:** `{event_type}`
{change_summary}
{overdue_note}
## Invoice Details
| Field          | Value |
|----------------|-------|
| Reference      | {rec.get('name', '—')} |
| Document Type  | {type_label} |
| Partner        | {partner} |
| Total Amount   | {amount_total:,.2f} |
| Amount Due     | {amount_due:,.2f} |
| Status         | {state_label} |
| Payment Status | {payment_label} |
| Assigned To    | {assigned_to} |
| Invoice Date   | {inv_date} |
| Due Date       | {due_date} |
| Source/Origin  | {origin} |

## Internal Notes
{rec.get('narration') or '_(none)_'}

## Previous State
{f'Was: State=**{prev_state}**, Payment=**{prev_pay}**' if prev else '_No previous state — newly detected record._'}

## Suggested Actions
Consider what response is appropriate. Examples:
- Send payment reminder to customer
- Register payment in Odoo after receiving funds
- Follow up on overdue invoice
- Verify vendor bill details before approving payment

## Raw Reference
- Odoo Model: `account.move`
- Record ID: `{rec['id']}`
- Write Date: `{rec.get('write_date', '')}`
"""
        filepath = self.needs_action / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info("Created: %s", filename)
        return filepath


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("odoo_watcher.py starting — Odoo Sense Component (XML-RPC)")
    logger.info("Vault: %s", VAULT_PATH)
    logger.info("Config: %s", CONFIG_PATH)
    logger.info("Poll interval: %ds", CHECK_INTERVAL)
    logger.info("Watching: Sales Orders + Invoices/Bills")
    logger.info("=" * 60)

    watcher = OdooWatcher()
    watcher.run()


if __name__ == "__main__":
    main()
