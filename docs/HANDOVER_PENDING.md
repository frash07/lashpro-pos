# Handover items requiring live access or owner evidence

The code changes in this branch are not a production deployment. Complete and record the following before handover.

## Fly.io and release controls

- Scan every branch, tag and commit in Git history for credentials, including M-Pesa, SMTP, Sentry, payment and database values. Rotate any credential that was ever committed. Store production credentials only with `fly secrets set` (or the approved secret manager), then confirm both apps receive the required secrets without printing values.
- From the Fly organization, verify `lashpro-api` has no public IP and `lashpro-web` exposes only the intended web IPs. The repository has no standalone API service; verify its actual app names and machine configuration.
- Confirm Fly certificates are issued and valid for `lashproke.cc` and `pos.lashproke.cc`; smoke-test HTTPS redirects, `/health`, `/healthz` and `/readyz` on both production apps.
- Confirm production and staging are in separate Fly organizations, remove former contractors, review organization and GitHub deploy-token access, and name current owners.
- Apply and verify the `jnb` region change with the live Fly machines and Neon database. The repository configuration alone does not move deployed machines or database compute.
- Set and verify a daily encrypted Neon export to storage outside Neon, retain evidence, and restore it to an isolated staging database at least quarterly. Neon is used here, so Fly volume snapshots do not back up the database.
- Configure Sentry DSN, uptime checks, retained external logs, and alerts for CPU, egress and authentication failures. Trigger each alert and retain proof that the on-call recipient receives it.
- Configure SMTP and `OPERATIONS_NOTIFICATION_EMAIL`, then send a test booking and storefront order. Confirm customer acknowledgement and staff notification delivery.

## Identity, privacy and fraud controls

- Enable and test manager two-factor authentication. The repository currently has role-based owner/manager/cashier permissions and a 15-minute idle session, but no manager 2FA.
- Verify that voids, discounts, refunds, cash adjustments and stock adjustments each create immutable audit events with actor, approver, reason and timestamps.
- Have Kenyan privacy counsel/ODPC confirm the business's exemption status before representing it as a legal conclusion. The ODPC FAQ describes thresholds for small controllers but also lists activities, including education, that affect exemption. Lashpro's academy/training activity needs specific review.
- Confirm the public legal identity, business contacts, privacy-policy contact route, and the owner's approval of the published privacy policy. This repository cannot independently verify the registered name or exemption status.
- Decide and implement protection for customer phone numbers at rest and separate consent timestamps from cookie/session records. Current customer phone fields are not encrypted.
- Confirm the Paybill and account number with the business owner before displaying them in production; perform a low-value manual payment and manager reconciliation rehearsal.

## Business operations and acceptance

- Confirm active providers and their actual weekly hours. Booking slots are clamped to 09:00–18:00 East Africa Time, but calendars and provider hours still need live acceptance.
- Run the CI workflow on this branch. It now includes Ruff checks, Django tests and a Trivy image scan. The new tests cover VAT extraction and manager-approved refund/restock; this local environment did not provide a usable Python runtime during authoring, so they have not been run here.
- Complete an offline queued-sale conflict-resolution rehearsal on disposable data. The existing offline client needs scenario testing across duplicate submission, stock conflicts and cross-terminal sync.
- Test checkout, manual M-Pesa reconciliation, receipts, password reset, booking/order emails, stock receive, refund and restore procedures in staging with named cashier and manager accounts.
- Confirm Trivy and the rolling deployment succeed against the exact production image, then use the documented manual production release gate.
- The repository is Django-based and has no Flutter web client. Flutter source-map/build-flavor work is out of scope unless a separate Flutter repository exists.

