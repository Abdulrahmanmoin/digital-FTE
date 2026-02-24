import xmlrpc.client
import json
from pathlib import Path
from datetime import datetime, timedelta

CONFIG_PATH = Path("credentials/odoo_config.json")

def get_odoo_data():
    if not CONFIG_PATH.exists():
        return "Config not found"
    
    cfg = json.loads(CONFIG_PATH.read_text())
    url = cfg["url"].rstrip("/")
    db = cfg["database"]
    username = cfg["username"]
    api_key = cfg.get("password") or cfg.get("api_key")
    
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, api_key, {})
    if not uid:
        return "Auth failed"
    
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    
    # 1. Total Sales (Confirmed)
    sales = models.execute_kw(db, uid, api_key, 'sale.order', 'search_read', [[['state', '=', 'sale']]], {'fields': ['amount_total']})
    total_sales = sum(s['amount_total'] for s in sales)
    
    # 2. Overdue Invoices
    today = datetime.now().strftime('%Y-%m-%d')
    overdue = models.execute_kw(db, uid, api_key, 'account.move', 'search_read', [[['state', '=', 'posted'], ['payment_state', '!=', 'paid'], ['invoice_date_due', '<', today]]], {'fields': ['amount_residual']})
    total_overdue = sum(i['amount_residual'] for i in overdue)
    
    return {
        "total_sales": total_sales,
        "sales_count": len(sales),
        "total_overdue": total_overdue,
        "overdue_count": len(overdue)
    }

if __name__ == "__main__":
    print(json.dumps(get_odoo_data()))
