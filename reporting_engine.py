"""
reporting_engine.py - Business Reporting & Analytics Component

Responsibility:
- Aggregates business data from Odoo (Sales, Invoices)
- Aggregates activity data from the Vault (Done/ tasks)
- Generates periodic business reports in /Reports
- Updates the live Metrics section in Dashboard.md
"""

import json
import logging
import os
import re
import xmlrpc.client
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
VAULT_PATH = BASE_DIR / "AI_Employee_Vault"
REPORTS_PATH = VAULT_PATH / "Reports"
DASHBOARD_PATH = VAULT_PATH / "Dashboard.md"
CREDENTIALS_DIR = BASE_DIR / "credentials"
ODOO_CONFIG_PATH = CREDENTIALS_DIR / "odoo_config.json"
DONE_DIR = VAULT_PATH / "Done"

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
REPORTS_PATH.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] reporting_engine - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "reporting_engine.log", encoding="utf-8"),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger("reporting_engine")

# ---------------------------------------------------------------------------
# Data Collection: Odoo
# ---------------------------------------------------------------------------

class OdooReporter:
    def __init__(self, config_path):
        self.config_path = config_path
        self.uid = None
        self.models = None
        self.db = ""
        self.api_key = ""
        self.connected = False
        self._connect()

    def _connect(self):
        if not self.config_path.exists():
            logger.error(f"Odoo config not found at {self.config_path}")
            return
        try:
            cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
            url = cfg["url"].rstrip("/")
            self.db = cfg["database"]
            username = cfg["username"]
            self.api_key = cfg.get("password") or cfg.get("api_key", "")
            
            common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
            self.uid = common.authenticate(self.db, username, self.api_key, {})
            if self.uid:
                self.models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
                self.connected = True
                logger.info("Connected to Odoo for reporting.")
            else:
                logger.error("Odoo authentication failed.")
        except Exception as e:
            logger.error(f"Failed to connect to Odoo: {e}")

    def get_financial_summary(self):
        if not self.connected:
            return None
        
        try:
            # Sales Stats
            sales = self.models.execute_kw(
                self.db, self.uid, self.api_key,
                'sale.order', 'search_read',
                [[['state', 'in', ['sale', 'done']]]],
                {'fields': ['amount_total', 'date_order']}
            )
            total_revenue = sum(s['amount_total'] for s in sales)
            
            # Outstanding / Overdue Invoices
            today = datetime.now().strftime('%Y-%m-%d')
            invoices = self.models.execute_kw(
                self.db, self.uid, self.api_key,
                'account.move', 'search_read',
                [[['state', '=', 'posted'], ['payment_state', '!=', 'paid'], ['move_type', '=', 'out_invoice']]],
                {'fields': ['amount_residual', 'invoice_date_due']}
            )
            total_outstanding = sum(i['amount_residual'] for i in invoices)
            overdue_invoices = [i for i in invoices if i['invoice_date_due'] and i['invoice_date_due'] < today]
            total_overdue = sum(i['amount_residual'] for i in overdue_invoices)

            return {
                "revenue": total_revenue,
                "sales_count": len(sales),
                "outstanding": total_outstanding,
                "overdue": total_overdue,
                "overdue_count": len(overdue_invoices)
            }
        except Exception as e:
            logger.error(f"Error fetching Odoo financial stats: {e}")
            return None

# ---------------------------------------------------------------------------
# Data Collection: Activity (Done Folder)
# ---------------------------------------------------------------------------

def get_activity_stats(lookback_days=7):
    stats = {
        "emails_sent": 0,
        "tweets_processed": 0,
        "linkedin_posts": 0,
        "odoo_tasks": 0,
        "total_actions": 0
    }
    
    if not DONE_DIR.exists():
        return stats
    
    cutoff = datetime.now() - timedelta(days=lookback_days)
    
    for file in DONE_DIR.glob("*.md"):
        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        if mtime < cutoff:
            continue
            
        stats["total_actions"] += 1
        name = file.name.upper()
        if "EMAIL" in name:
            stats["emails_sent"] += 1
        elif "TWEET" in name:
            stats["tweets_processed"] += 1
        elif "LINKEDIN" in name:
            stats["linkedin_posts"] += 1
        elif "ODOO" in name:
            stats["odoo_tasks"] += 1
            
    return stats

# ---------------------------------------------------------------------------
# Dashboard & Report Generation
# ---------------------------------------------------------------------------

def generate_report(financials, activity):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_name = f"Report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    
    financial_section = "_(No Odoo data available)_"
    if financials:
        financial_section = f"""### 💰 Financial Performance
- **Total Lifetime Revenue:** ${financials['revenue']:,.2f}
- **Confirmed Sales Count:** {financials['sales_count']}
- **Total Outstanding:** ${financials['outstanding']:,.2f}
- **Total Overdue:** ${financials['overdue']:,.2f} ({financials['overdue_count']} invoices)
"""

    content = f"""---
type: business_report
generated_at: "{timestamp}"
---

# 📈 Business Performance Report — {datetime.now().strftime('%B %d, %Y')}

## 🚀 Executive Summary
Generated on {timestamp}. This report aggregates data from Odoo ERP and system activity logs.

{financial_section}

### ⚡ Activity Summary (Last 7 Days)
- **Total Actions Executed:** {activity['total_actions']}
- **Emails Sent:** {activity['emails_sent']}
- **Tweets Processed:** {activity['tweets_processed']}
- **LinkedIn Engagements:** {activity['linkedin_posts']}
- **Odoo Operations:** {activity['odoo_tasks']}

---
*End of Report*
"""
    
    report_file = REPORTS_PATH / report_name
    report_file.write_text(content, encoding="utf-8")
    logger.info(f"Generated report: {report_name}")
    return content

def update_dashboard(financials, activity):
    if not DASHBOARD_PATH.exists():
        return
    
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    
    rev = f"${financials['revenue']:,.2f}" if financials else "$—"
    overdue = f"${financials['overdue']:,.2f}" if financials else "$—"
    
    metrics_header = "## 📊 Top-line Metrics"
    metrics_content = f"""
{metrics_header}
| Metric | Value |
| :--- | :--- |
| **Total Revenue** | {rev} |
| **Overdue Amount** | {overdue} |
| **Weekly Actions** | {activity['total_actions']} |
| **Pending Approval** | {len(list((VAULT_PATH / 'Pending_Approval').glob('*.md')))} |
"""

    # Replace or Append Metrics section
    if metrics_header in content:
        # Simple regex to replace up to the next header or end of file
        content = re.sub(rf"{metrics_header}.*?(?=\n## |$)", metrics_content.strip(), content, flags=re.DOTALL)
    else:
        # Append before "Recent Activity" or at the end
        if "## Recent Activity" in content:
            content = content.replace("## Recent Activity", metrics_content + "\n\n## Recent Activity")
        else:
            content += "\n\n" + metrics_content

    DASHBOARD_PATH.write_text(content, encoding="utf-8")
    logger.info("Updated Dashboard with latest metrics.")

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

REPORT_INTERVAL = 3600  # 1 Hour

def main():
    logger.info("=" * 60)
    logger.info("reporting_engine.py starting — Business Reporting & Analytics")
    logger.info(f"Report interval: {REPORT_INTERVAL}s")
    logger.info("=" * 60)
    
    while True:
        try:
            logger.info("Starting reporting cycle...")
            
            # 1. Collect Data
            odoo = OdooReporter(ODOO_CONFIG_PATH)
            financials = odoo.get_financial_summary()
            activity = get_activity_stats()
            
            # 2. Generate Report
            generate_report(financials, activity)
            
            # 3. Update Dashboard
            update_dashboard(financials, activity)
            
            logger.info(f"Reporting cycle complete. Sleeping for {REPORT_INTERVAL}s...")
        except Exception as e:
            logger.error(f"Error in reporting loop: {e}")
        
        time.sleep(REPORT_INTERVAL)

if __name__ == "__main__":
    import time
    main()
