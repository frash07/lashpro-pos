# LashPro POS product roadmap from Alpha feedback

This roadmap separates the completed Alpha usability fixes from larger inventory and accounting capabilities that need explicit business rules and a controlled data migration. Items in the later phases are planned, not yet implemented by the checkout/receipt/password-recovery change set.

## Phase 1 — Close current Alpha feedback

- **Cash change:** accept the amount handed over in cash, allocate only the sale balance, calculate change, and keep cash-session expected balances net of change returned.
- **Receipts:** offer a downloadable PDF and browser print flow; include technician assignment and clearly separate cash tender, change, confirmed payments and unverified M-Pesa.
- **Technician commission visibility:** show the technician on the service and commission ledger and display earned, reversed, paid, pending and available amounts per technician to managers.
- **Inventory navigation and low-stock alert:** add admin quick links for products, receipts, stock movements, adjustment requests and service consumables; surface items at/below configured reorder level.
- **Account security:** provide authenticated password change and email-based reset when SMTP is configured. Until SMTP is configured, the reset form directs staff to a manager instead of leaking reset links to logs.
- **Checkout speed:** show the live cart/payment summary, preview change, offer “Fill exact balance”, and keep M-Pesa allocation separate from cash tender.

## Phase 2 — Inventory and staff operations

### Dual retail / professional products
- Add an explicit product classification: retail sale, professional-use-only, or both.
- Exclude professional-only stock from retail checkout while allowing it to be consumed through a service recipe / consumables ledger.
- Keep cost, selling price, on-hand quantity and reorder level separate. Decide whether professional-use product can be sold to staff or wholesale customers before implementing those routes.
- Track transfers, wastage, free issues, returns and approved adjustments as immutable, actor-attributed stock movements; never edit stock history directly.

### Suppliers and purchasing
- Add supplier records, supplier contacts/terms, purchase orders, partial receipts, supplier bills, credit notes and outstanding supplier balances.
- Stock increases only on an accepted receipt, not merely when an order is created. Receiving records supplier, quantities, unit costs, date and receiving staff.
- Define a stable integration contract (API, CSV import, or email/manual workflow) per supplier before promising direct supplier integration. Store external IDs and idempotency keys for imports.
- Generate in-app low-stock alerts from configurable reorder levels; add email notifications only after recipients, thresholds, de-duplication and delivery failure handling are agreed.

### Staff and commission performance
- Add a dedicated staff workflow for creating/deactivating accounts, reset/reinvite, role assignment, and a review log for permission changes.
- Add per-technician metrics by date range: completed service count, gross service value, eligible commission, reversals, payouts, pending payout requests and available balance.
- Keep commission earned on service completion, preserve its rate snapshot, and reverse it via a separate ledger entry when an approved refund requires it.

## Phase 3 — Accounting foundations

- Define a chart of accounts and immutable journal entries with debit and credit lines. Enforce that each posted journal is balanced (total debits = total credits) inside one database transaction.
- Map source events explicitly: sales, split tenders, cash change, M-Pesa verification, stock purchases, cost of goods sold, returns, expenses, commission accruals and payouts.
- Add accounts receivable for balances due, accounts payable for supplier bills, ageing reports, bank/cash clearing and daily control checks.
- Build reconciliation controls across the sales subledger, payment allocations, cash sessions, M-Pesa statements, inventory valuation, commissions and the general ledger.
- Migrate with opening balances and reproducible reconciliation reports. Existing payment and inventory records must remain traceable to their originating events.
- Do not treat a reporting total or a single transaction table as a double-entry ledger. This phase needs accounting review and end-to-end tests before it can be used for real financial reporting.

## Phase 4 — Price lists, promotions and free issues

- Model price lists for customer groups and selling situations (retail, professional/wholesale, staff, promotions); define precedence and effective start/end dates.
- Model promotion eligibility, product/service scope, quantity limits, stacking rules, discount authority, reason, and approval.
- Record free issues as explicit zero-price sale/issue lines with a reason and stock movement. They must reduce inventory and appear in audit/reporting without inflating cash collection.
- Snapshot the applied price list, promotion and approval on each sale line so later catalog changes do not rewrite historical receipts.

## Phase 5 — Audit and operations controls

- Expand the existing audit trail to cover staff and permission changes, supplier/order/bill changes, price/promotion edits, product classification, stock adjustments, free issues, exports, login/lockout/recovery events and accounting journal posting/reversal.
- Record actor, timestamp, reason/approval, object ID and before/after state for material changes. Keep financial and stock ledgers append-only; correct errors with reversal entries rather than silent edits.
- Add daily control-check dashboards and alerts with a named owner, tolerances and a documented exception-resolution process.

## Release gates for the later phases

Each phase needs model and migration tests, authorization tests by role, concurrency/idempotency tests, audit assertions, reconciliation examples, backup/restore rehearsal and a reviewed migration plan. Supplier/API integration and the general ledger must not be enabled against live data until source-of-truth ownership, accounting treatment and failure recovery are agreed.
