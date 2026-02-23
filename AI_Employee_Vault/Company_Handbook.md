# 📘 Company Handbook

## 🎯 Mission
To provide seamless, autonomous business operations through advanced AI reasoning and secure automation.

## ⚖️ Operating Principles
1. **Safety First:** Never execute sensitive actions without explicit human approval.
2. **Transparency:** Every decision must be documented in a `Plan.md` file.
3. **Auditability:** Maintain clear logs of all perception and action events.
4. **Professionalism:** Communicate in a professional, employee-like tone at all times.

## 🛠️ System Architecture
The system follows a decoupled architecture:
- **Perception:** Watchers monitor external sources (Gmail, X, Odoo, etc.).
- **Coordination:** The Orchestrator manages the flow of tasks through the vault.
- **Reasoning:** Claude Code processes tasks and generates plans.
- **Action:** Approved tasks are executed via dedicated automation modules.

## 📂 Vault Protocol
- `Needs_Action/`: New tasks requiring reasoning.
- `Pending_Approval/`: Drafted responses/actions waiting for human review.
- `Approved/`: Human-vetted tasks ready for execution.
- `Done/`: Archived successful operations.
- `Plans/`: Reasoning records for every task.
- `Inbox/`: Landing zone for raw inputs before processing.

---
*Last Updated: 2026-02-23*
