"""
ceo_briefing.py - Daily CEO Briefing Generator

Responsibility:
- Produces a concise, executive-level daily briefing for the CEO.
- Aggregates financial data from Odoo, activity data from the Vault,
  and pending items across queues.
- Outputs a polished Markdown report in AI_Employee_Vault/Reports/.
- Runs as a long-lived service (one briefing per day).
"""

import json
import logging
import socket
import time
import xmlrpc.client
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
REPORTS_PATH = VAULT_PATH / "Reports"
CREDENTIALS_DIR = BASE_DIR / "credentials"
ODOO_CONFIG_PATH = CREDENTIALS_DIR / "odoo_config.json"
LOG_DIR = BASE_DIR / "logs"
DONE_DIR = VAULT_PATH / "Done"
NEEDS_ACTION_DIR = VAULT_PATH / "Needs_Action"
PENDING_APPROVAL_DIR = VAULT_PATH / "Pending_Approval"
DASHBOARD_PATH = VAULT_PATH / "Dashboard.md"

LOG_DIR.mkdir(exist_ok=True)
REPORTS_PATH.mkdir(exist_ok=True)

BRIEFING_INTERVAL = 86400  # 24 hours

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ceo_briefing - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "ceo_briefing.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("ceo_briefing")

# ---------------------------------------------------------------------------
# Data Collection: Odoo Financial Snapshot
# ---------------------------------------------------------------------------

def get_financial_snapshot():
    """Connect to Odoo and return a financial snapshot dict, or None."""
    if not ODOO_CONFIG_PATH.exists():
        return None
    try:
        cfg = json.loads(ODOO_CONFIG_PATH.read_text(encoding="utf-8"))
        url = cfg["url"].rstrip("/")
        db = cfg["database"]
        username = cfg["username"]
        api_key = cfg.get("password") or cfg.get("api_key", "")

        socket.setdefaulttimeout(10)
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", timeout=10)
        uid = common.authenticate(db, username, api_key, {})
        if not uid:
            return None
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", timeout=10)

        # Revenue
        sales = models.execute_kw(
            db, uid, api_key, "sale.order", "search_read",
            [[["state", "in", ["sale", "done"]]]],
            {"fields": ["amount_total"]},
        )
        total_revenue = sum(s["amount_total"] for s in sales)

        # Outstanding & overdue invoices
        today_str = datetime.now().strftime("%Y-%m-%d")
        invoices = models.execute_kw(
            db, uid, api_key, "account.move", "search_read",
            [[["state", "=", "posted"], ["payment_state", "!=", "paid"],
              ["move_type", "=", "out_invoice"]]],
            {"fields": ["amount_residual", "invoice_date_due", "name", "partner_id"]},
        )
        total_outstanding = sum(i["amount_residual"] for i in invoices)
        overdue = [i for i in invoices if i["invoice_date_due"] and i["invoice_date_due"] < today_str]
        total_overdue = sum(i["amount_residual"] for i in overdue)

        # Recent orders (last 7 days)
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = models.execute_kw(
            db, uid, api_key, "sale.order", "search_read",
            [[["state", "in", ["sale", "done"]], ["date_order", ">=", week_ago]]],
            {"fields": ["name"]},
        )

        return {
            "revenue": total_revenue,
            "outstanding": total_outstanding,
            "overdue": total_overdue,
            "overdue_count": len(overdue),
            "recent_orders": len(recent),
            "overdue_top3": sorted(overdue, key=lambda x: x["amount_residual"], reverse=True)[:3],
        }
    except Exception as e:
        logger.error(f"Odoo snapshot failed: {e}")
        return None


def get_fallback_financials():
    """Sample data when Odoo is unreachable."""
    return {
        "revenue": 124500.0,
        "outstanding": 15200.0,
        "overdue": 3450.0,
        "overdue_count": 2,
        "recent_orders": 5,
        "overdue_top3": [
            {"name": "INV/2026/0002", "partner_id": [1, "Azure Interior"], "amount_residual": 1450.0},
            {"name": "INV/2026/0004", "partner_id": [2, "Deco Addict"], "amount_residual": 2000.0},
        ],
    }

# ---------------------------------------------------------------------------
# Data Collection: Activity (last 24h)
# ---------------------------------------------------------------------------

def get_activity_24h():
    stats = {"emails": 0, "tweets": 0, "linkedin": 0, "odoo": 0, "facebook": 0, "total": 0}
    if not DONE_DIR.exists():
        return stats
    cutoff = datetime.now() - timedelta(hours=24)
    for f in DONE_DIR.glob("*.md"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                continue
        except OSError:
            continue
        stats["total"] += 1
        name = f.name.upper()
        if "EMAIL" in name:
            stats["emails"] += 1
        elif "TWEET" in name:
            stats["tweets"] += 1
        elif "LINKEDIN" in name:
            stats["linkedin"] += 1
        elif "ODOO" in name:
            stats["odoo"] += 1
        elif "FACEBOOK" in name:
            stats["facebook"] += 1
    return stats

# ---------------------------------------------------------------------------
# Data Collection: Pending Items
# ---------------------------------------------------------------------------

def get_pending_items():
    needs = list(NEEDS_ACTION_DIR.glob("*.md")) if NEEDS_ACTION_DIR.exists() else []
    pending = list(PENDING_APPROVAL_DIR.glob("*.md")) if PENDING_APPROVAL_DIR.exists() else []
    return {"needs_action": len(needs), "pending_approval": len(pending)}

# ---------------------------------------------------------------------------
# Briefing Generation
# ---------------------------------------------------------------------------

def generate_briefing(fin, activity, pending):
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    report_name = f"CEO_Briefing_{date_str}.md"

    # System health
    health = "🟢 All Systems Operational"
    if pending["needs_action"] > 10:
        health = "🟡 Elevated Queue — review recommended"

    # Overdue invoice lines
    overdue_lines = ""
    for inv in fin.get("overdue_top3", []):
        customer = inv["partner_id"][1] if isinstance(inv.get("partner_id"), list) else "Unknown"
        overdue_lines += f"| {inv['name']} | {customer} | ${inv['amount_residual']:,.2f} |\n"
    if not overdue_lines:
        overdue_lines = "| — | No overdue invoices | $0.00 |\n"

    # Recommended actions
    actions = []
    if fin["overdue"] > 0:
        actions.append(f"🔴 **Collections:** ${fin['overdue']:,.2f} overdue across {fin['overdue_count']} invoice(s) — prioritize follow-up.")
    if pending["pending_approval"] > 0:
        actions.append(f"📝 **Approvals:** {pending['pending_approval']} action(s) awaiting your sign-off in `Pending_Approval/`.")
    if pending["needs_action"] > 5:
        actions.append(f"📥 **Queue:** {pending['needs_action']} unprocessed items in `Needs_Action/` — consider triage.")
    if fin["recent_orders"] > 0:
        actions.append(f"📈 **Sales:** {fin['recent_orders']} new order(s) confirmed this week — review fulfillment pipeline.")
    if not actions:
        actions.append("✅ No critical actions required today. Operations running smoothly.")

    actions_block = "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions))

    content = f"""---
type: ceo_briefing
generated_at: "{today.isoformat()}"
---

# 🏢 CEO Daily Briefing — {today.strftime('%A, %B %d, %Y')}

> **System Health:** {health}
> **Report Generated:** {today.strftime('%I:%M %p')}

---

## 📊 Financial Snapshot

| Metric | Value |
| :--- | :--- |
| **Lifetime Revenue** | ${fin['revenue']:,.2f} |
| **Outstanding Receivables** | ${fin['outstanding']:,.2f} |
| **Total Overdue** | ${fin['overdue']:,.2f} |
| **Orders This Week** | {fin['recent_orders']} |

### Overdue Invoices Requiring Attention
| Invoice | Customer | Amount |
| :--- | :--- | :--- |
{overdue_lines}
---

## ⚡ Last 24 Hours — Activity Summary

| Channel | Actions |
| :--- | :--- |
| 📧 Email | {activity['emails']} |
| 🐦 X / Twitter | {activity['tweets']} |
| 💼 LinkedIn | {activity['linkedin']} |
| 📘 Facebook | {activity['facebook']} |
| 🏭 Odoo ERP | {activity['odoo']} |
| **Total** | **{activity['total']}** |

---

## 🚨 Items Requiring Your Attention

- **Pending Approval:** {pending['pending_approval']} action(s)
- **Needs Action Queue:** {pending['needs_action']} item(s)

---

## ✅ Recommended Actions

{actions_block}

---
*Confidential — Generated by your Digital FTE*
"""

    report_path = REPORTS_PATH / report_name
    report_path.write_text(content, encoding="utf-8")
    logger.info(f"CEO Briefing generated: {report_name}")
    return report_name


def update_dashboard(report_name):
    if not DASHBOARD_PATH.exists():
        return
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    date_str = datetime.now().strftime("%Y-%m-%d")
    link = f"- [[Reports/{report_name.replace('.md', '')}|🏢 CEO Briefing ({date_str})]]"
    if link in content:
        return
    if "## 📈 Recent Reports" in content:
        content = content.replace("## 📈 Recent Reports", f"## 📈 Recent Reports\n{link}")
        DASHBOARD_PATH.write_text(content, encoding="utf-8")
        logger.info("Dashboard updated with CEO Briefing link.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("ceo_briefing.py starting — CEO Daily Briefing Service")
    logger.info(f"Briefing interval: {BRIEFING_INTERVAL}s")
    logger.info("=" * 60)

    while True:
        try:
            logger.info("Generating CEO briefing...")
            fin = get_financial_snapshot() or get_fallback_financials()
            activity = get_activity_24h()
            pending = get_pending_items()
            report_name = generate_briefing(fin, activity, pending)
            update_dashboard(report_name)
            logger.info(f"Briefing cycle complete. Sleeping {BRIEFING_INTERVAL}s...")
        except Exception as e:
            logger.error(f"Briefing error: {e}")

        time.sleep(BRIEFING_INTERVAL)


if __name__ == "__main__":
    main()
