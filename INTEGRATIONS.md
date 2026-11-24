# LashPro integrations — pilot setup

The owner/manager API form is available from **Admin Suite → API & Payment Integrations** at /admin-suite/integrations/.

Credentials are encrypted at rest in the core_integrationsettings table. The encryption key is deterministically derived from Django's DJANGO_SECRET_KEY; keep that secret stable and backed up. Password/API-key fields are write-only. Leaving one blank preserves the stored value; use the corresponding remove checkbox to clear it.

## Booking notifications

A newly-created appointment request sends an email and, when configured, an SMS and WhatsApp template notification. A separate update is sent when staff changes the status to Confirmed or Cancelled. A booking request is not described as confirmed.

- **Email:** enter an SMTP host, port, username/password and sender address. Use an app password where the mail host requires one.
- **SMS:** select Africa's Talking, enter the application username and API key. Use sandbox mode while testing. A live sender ID may need provider approval.
- **WhatsApp:** add the Meta Cloud API access token and WhatsApp Business phone-number ID. Create and approve three utility templates (request received, confirmed, cancelled) in WhatsApp Manager, then enter their exact names. Each template body must accept four text variables, in order: customer name, service name, date, and time/provider.

Provider delivery is best-effort: a provider outage is logged but does not undo or block a booking. Production booking emails are not sent through the console backend when SMTP is absent, to avoid logging customer information. Customers should still see the on-screen booking reference.

## Safaricom Daraja STK Push

1. Create/enable a Daraja app and obtain its Consumer Key and Consumer Secret.
2. Add the business short code, Lipa Na M-Pesa passkey, and select PayBill or Buy Goods according to the shortcode's product.
3. Test with sandbox credentials first; use production credentials only after Safaricom enables the production shortcode.
4. Confirm that the POS public origin is set correctly in POS_BASE_URL. The callback is generated under /payments/mpesa/stk/callback/<unguessable-token>/ and must be reachable over HTTPS.
5. Run the payment flow from POS checkout or the sale-balance screen. The payment stays unverified until a callback with a successful result and M-Pesa receipt number is received. A timeout is treated as an unknown outcome; do not immediately submit another prompt.

This implementation deliberately does not edit immutable transaction references. The Safaricom receipt is stored on the STK callback record and the customer-facing receipt displays its masked value.

## KRA eTIMS

The owner form stores the taxpayer PIN, branch, device identifier, communication key and the selected environment as encrypted setup data. **It does not submit invoices to KRA and must not be presented as an active eTIMS integration.** KRA OSCU/VSCU self-integration requires the correct technical specification, testing and KRA vetting/certification, plus taxpayer/device activation. The actual invoice payload, receipt response, offline queue/retry policy and fiscal reconciliation must be implemented and tested against the approved KRA protocol before enabling production submission.

## Production acceptance

Apply the migrations (core.0002_integrationsettings, payments.0009_mpesa_stk_push and payments.0010_unique_stk_receipt) as part of the normal release process, install the requirements, and verify the Fly callback URL and public POS_BASE_URL. Keep payment collection in pilot until sandbox STK prompts, callback races, duplicate receipt protection and the POS checkout flow have been tested with the Daraja sandbox account.


## WhatsApp catalogue commerce

See [WHATSAPP_COMMERCE.md](WHATSAPP_COMMERCE.md) for the WhatsApp Business App coexistence onboarding, Meta catalogue credentials, webhook verification, automatic stock publication and inbound catalogue-order workflow. The existing WhatsApp booking-notification integration remains supported.


## Direct M-Pesa Paybill / Till payments (C2B)

LashPro can receive customer-initiated Paybill or Buy Goods/Till payments separately from STK Push. Configure **C2B callback shortcodes** in Admin Suite → API & Payment Integrations. Enter one receiving shortcode per line. For Buy Goods accounts, confirm with Safaricom which shortcode must be used for callback registration; some account structures route through a child shortcode.

Save the settings, then select **Register C2B callbacks**. LashPro registers the C2B v2 confirmation and validation URLs for each configured shortcode using ResponseType=Completed. The confirmation callback is a distinct C2B payload, not the STK Body.stkCallback payload.

A C2B confirmation creates a Safaricom-confirmed M-Pesa transaction in LashPro. It is intentionally left **unallocated** until a cashier opens Payments → Incoming M-Pesa, asks the customer to confirm the payer name displayed, selects the matching transaction and allocates it to a completed sale. Cashiers can allocate only to their own sales; owners and managers can allocate to any completed sale. A receipt can be allocated only once, and payments larger than the sale balance remain unallocated.

C2B callback data is idempotent by M-Pesa receipt number. LashPro stores the payer name fields supplied by Safaricom and a masked/withheld phone display; it does not retain the full MSISDN or the raw callback body. The C2B callback token is stored with the encrypted integration configuration.

C2B confirmation proves that the money reached the configured shortcode. Cashier allocation is a separate, audited action that links the received payment to a sale. It must not be performed solely because the amount matches.


## Canonical production callbacks

Set POS_BASE_URL=https://pos.lashproke.cc and STOREFRONT_BASE_URL=https://lashproke.cc on both Fly apps. Confirm TLS and DNS before registering callbacks. Register C2B URLs anew after the domain change; preserve old Fly aliases while outstanding STK requests settle. Never paste callback tokens or live credentials into issues or logs. Use a controlled low-value live transaction only after sandbox acceptance and business approval. Match every recorded receipt to the business's Safaricom statement; investigate UNKNOWN or pending requests without resending a prompt. See [docs/CLIENT_HANDOVER.md](docs/CLIENT_HANDOVER.md) for the integration acceptance matrix.
