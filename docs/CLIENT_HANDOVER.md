# Client handover evidence register

Status: live acceptance is not certified. Record date, accountable owner, redacted evidence link and result for every item. Never attach credentials, customer data or unmasked callback URLs.

## Release and infrastructure

- [ ] Approve exact commit; required CI checks green; protect main and settle repository/IP ownership.
- [ ] Confirm paid Fly/Neon billing, machine and database region, least-privileged runtime access, and production app capacity.
- [ ] Configure https://lashproke.cc and https://pos.lashproke.cc with Fly certificates and DNS; confirm HTTPS and allowed hosts. Verify /readyz returns 200 on both.
- [ ] Verify both applications run the approved commit and connect to the same intended Neon branch using the disposable shared-database probe in DEPLOYMENT.md.
- [ ] Verify durable media, including recovered images and visibility after Machine replacement.
- [ ] Verify production checks and migrations, two independent named manager/owner accounts, removal of bootstrap secrets, synthetic data disabled.
- [ ] Record Neon retention; perform off-provider encrypted backup and restore to separate branch; reconcile totals and test restored app; agree RPO/RTO.
- [ ] Verify scheduler runs and expires disposable holds; test Sentry alerts and uptime monitoring.
- [ ] Confirm verified SMTP sender and password-reset email on both applications; confirm existing support@lashpro.ke mailbox or provision and approve a replacement at lashproke.cc before changing public support links.

## Payment and provider acceptance

- [ ] Daraja sandbox: STK success, rejection, cancellation, timeout, late/duplicate callback, callback correlation, wrong amount and duplicate receipt; confirm unknown outcomes are investigated without duplicate prompts.
- [ ] Confirm business-approved live shortcode and callback registrations on pos.lashproke.cc. Test controlled low-value live STK and C2B and reconcile to Safaricom statement.
- [ ] Confirm Paybill/Till inbox allocation permissions, correct payer/sale, no duplicate allocation, overpayment remains unallocated; establish escalation for unmatched funds.
- [ ] Verify Meta coexistence for existing WhatsApp number, webhook signature, catalogue mapping and stock sync; test duplicate and insufficient-stock orders and fulfilment. Check scheduled sync logs and queue.
- [ ] Verify booking notification email, SMS and WhatsApp templates (requested, confirmed, cancelled, expired); check delivered time in EAT.
- [ ] KRA eTIMS: not implemented. Agree separate compliant invoicing process or scoped certified integration before applicable fiscal use.

## Client acceptance

- [ ] Reconcile opening products, stock, cash, outstanding balances and staff/customer records. Do not load synthetic records into production.
- [ ] Browser/physical device smoke tests: retail and service checkout, change/split payments, refunds, receipts/printer, cash close/variance, stock receive/adjustments, commissions, expenses, reports, training enrolment, storefront registration/order/fulfilment, booking availability/expiry, role restrictions and password recovery.
- [ ] Confirm network interruption behaviour; POS requires connectivity for transaction processing.
- [ ] Complete legal/privacy checklist, approve public contact information and policies, train owner/manager/cashier/technician/trainer, agree support and escalation.
- [ ] Document provider account ownership and billing; transfer or grant appropriate client access without sharing passwords; approve release and rollback plan; obtain written client acceptance.

Do not mark a gate complete based on source code or a green CI run alone.
