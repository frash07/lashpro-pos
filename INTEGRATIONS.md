# LashPro integrations — pilot setup

The owner/manager API form is available from **Admin Suite → API & Payment Integrations** at /admin-suite/integrations/.

Credentials are encrypted at rest in the core_integrationsettings table. The encryption key is deterministically derived from Django's DJANGO_SECRET_KEY; keep that secret stable and backed up. Password/API-key fields are write-only. Leaving one blank preserves the stored value; use the corresponding remove checkbox to clear it.

## Booking notifications

A newly-created appointment request sends an email and, when configured, an SMS and WhatsApp template notification. A separate update is sent when staff changes the status to Confirmed or Cancelled. A booking request is not described as confirmed.

- **Email:** enter an SMTP host, port, username/password and sender address. Use an app password where the mail host requires one.
- **SMS:** select Africa's Talking, enter the application username and API key. Use sandbox mode while testing. A live sender ID may need provider approval.
- **WhatsApp:** add the Meta Cloud API access token and WhatsApp Business phone-number ID. Create and approve three utility templates (request received, confirmed, cancelled) in WhatsApp Manager, then enter their exact names. Each template body must accept four text variables, in order: customer name, service name, date, and time/provider.

Provider delivery is best-effort: a provider outage is logged but does not undo or block a booking. Customers should still see the on-screen booking reference.

## Safaricom Daraja STK Push

1. Create/enable a Daraja app and obtain its Consumer Key and Consumer Secret.
2. Add the business short code, Lipa Na M-Pesa passkey, and select PayBill or Buy Goods according to the shortcode's product.
3. Test with sandbox credentials first; use production credentials only after Safaricom enables the production shortcode.
4. Confirm that the POS public origin is set correctly in POS_BASE_URL. The callback is generated under /payments/mpesa/stk/callback/<unguessable-token>/ and must be reachable over HTTPS.
5. Run the payment flow from POS checkout or the sale-balance screen. The payment stays unverified until a callback with a successful result and M-Pesa receipt number is received. A timeout is treated as an unknown outcome; do not immediately submit another prompt.

This implementation deliberately does not edit immutable transaction references. The Safaricom receipt is stored on the STK callback record and the customer-facing receipt displays its masked value.

## KRA eTIMS

The owner form stores the taxpayer PIN, branch, device identifier, communication key and the selected environment as encrypted setup data. **It does not submit invoices to KRA and must not be presented as an active eTIMS integration.** KRA OSCU/VSCU self-integration requires the correct technical specification, testing and KRA vetting/certification, plus taxpayer/device activation. The actual invoice payload, receipt response, offline queue/retry policy and fiscal reconciliation must be implemented and tested against the approved KRA protocol before enabling production submission.

## Deploying the branch

Apply the migrations (core.0002_integrationsettings and payments.0009_mpesa_stk_push) as part of the normal release process, install the requirements, and verify the Fly callback URL and public POS_BASE_URL. Keep this branch in pilot until sandbox callbacks and all notification templates have been tested with real provider accounts.



## WhatsApp Business App coexistence, catalogue sync and orders

LashPro's WhatsApp commerce integration is designed to keep the owner's existing WhatsApp Business App and phone number in use while connecting that same number to Meta's WhatsApp Business Platform Cloud API through Meta's **Business App coexistence** onboarding flow. Do not remove the number from the WhatsApp Business App, delete the WhatsApp Business account, or register the number as a separate API-only number as a shortcut.

Meta currently documents an API solution for WhatsApp Business App users that supports use of the Business App and API with the same number. Availability is controlled by Meta and can depend on the Business Account, phone number, region and onboarding path. The owner must complete the Meta-hosted Embedded Signup/coexistence approval on the original phone. If Meta does not offer the coexistence option for this number, stop and review eligibility with Meta before changing the number or app.

### 1. Prepare the Meta business assets

The owner or authorised Meta Business administrator should:

1. Confirm the existing number is active in the WhatsApp Business App and that the owner can receive the in-app verification prompt.
2. Use a Meta app configured for the WhatsApp Business Platform and the **API solutions for WhatsApp Business app users / coexistence** onboarding flow.
3. Complete Meta's Embedded Signup with the existing WhatsApp Business Account and number. Keep the app installed and continue normal client conversations in the WhatsApp Business App.
4. Confirm the business catalogue is connected to the same WhatsApp Business Account. Keep the existing catalogue; do not create a replacement until its items have been mapped to LashPro.
5. Create a Meta system-user access token with the required WhatsApp messaging, WhatsApp Business management and catalogue-management access to the WABA and the catalogue.

Record these identifiers from Meta Business Manager / WhatsApp Manager / Commerce Manager:
- WhatsApp Business Account ID (WABA ID).
- WhatsApp Business Phone Number ID.
- Product catalogue ID.
- Meta app secret.
- System-user access token.
- A new, high-entropy webhook verification token chosen by the owner.

The access token, app secret and webhook verification token belong only in the owner-only LashPro **Admin Suite → API & Payment Integrations** form. They are encrypted at rest in the integration settings record. Never add them to source control, issue comments, screenshots or chat transcripts.

### 2. Configure the Meta webhook

The callback is:

`https://lashpro-pos.fly.dev/webhooks/whatsapp/`

In the Meta app's WhatsApp webhook settings:
- Set the callback URL above and the exact webhook verification token saved in LashPro.
- Subscribe the app/WABA to the `messages` field.
- Complete Meta's GET verification challenge.
- Confirm Meta sends signed POST webhooks. LashPro verifies `X-Hub-Signature-256` using the saved Meta app secret before it accepts an order.

The webhook persists catalogue `order` messages into a de-duplicated inbox and returns promptly. It does not attempt to create the order inside the Meta webhook request.

### 3. Match the existing catalogue before enabling updates

Meta's catalogue retailer ID (also called Content ID) is the key that joins a WhatsApp catalogue item to a LashPro product SKU. The existing catalogue may have retailer IDs that differ from LashPro SKUs; do not assume they match.

1. In LashPro, open **Admin Suite → API & Payment Integrations**.
2. Save the WABA ID, catalogue ID, phone-number ID, access token, app secret and webhook verification token.
3. Enable **Automatic WhatsApp catalogue synchronisation** only after Meta has completed coexistence onboarding and the correct catalogue has been connected to the WABA.
4. Use **Prepare / queue catalogue sync** to create mapping rows for existing products.
5. Open **Catalog → WhatsApp catalogue links** (`/admin/catalog/whatsappcatalogsync/`).
6. For each current catalogue item, enter the exact retailer ID from Meta Commerce Manager, select **Catalogue linked**, and save. Confirm the product name and SKU against Meta before linking.
7. Enable **Allow upsert** only when the retailer ID has been verified as an existing item in this catalogue. Leave it off for a new item so a retailer-ID collision fails safely instead of overwriting an unrelated listing.
8. Ensure each product has a public HTTPS product image. Meta requires a product image URL when creating/updating catalogue items.

New LashPro products created after catalogue synchronisation has been enabled are queued using their immutable LashPro SKU as the new retailer ID. Existing records are never guessed or mass-linked to a Meta item.

### 4. Synchronisation behaviour

- LashPro/Neon is the inventory source of truth. The WhatsApp catalogue is a customer-facing projection, not an independent stock ledger.
- Product name, KSh selling price, public image, active state and sellable inventory are pushed to Meta.
- Sellable inventory is physical on-hand stock less active online-order reservations. A WhatsApp/web reservation therefore reduces displayed availability before physical stock is deducted.
- POS stock sales, supplier receipts, approved adjustments, product edits and online reservation changes queue a catalogue refresh.
- A separate `whatsapp_worker` Fly process handles catalogue calls and incoming order imports; the web request process does not wait for Meta.
- Failed syncs are retried with backoff and visible on the WhatsApp catalogue mapping record. Items requiring a new retailer-ID match or missing product image must be corrected by an owner/manager.

### 5. WhatsApp catalogue orders

When a customer sends a cart from the connected Meta catalogue, Meta posts an order message containing the catalogue ID and each product's `product_retailer_id`, quantity, item price and currency.

LashPro imports the order only when:
- the webhook signature is valid;
- the catalogue ID matches the configured WABA catalogue;
- every retailer ID is mapped to an active LashPro product;
- every line is in KES and the Meta unit price still matches the current LashPro price; and
- the requested quantities are available after accounting for existing reservations.

The importer calls the same atomic online-order service as the storefront. It creates a **WhatsApp** channel order in **Awaiting staff confirmation**, stores the Meta message ID as an external reference, and reserves stock for the normal public order-hold window. The webhook message ID is unique, so repeated Meta deliveries do not create a second order.

A product mapping, price, currency or stock problem is retained in **WhatsApp order import inbox** (`/admin/storefront/whatsapporderinbox/`) for staff review. After correcting the cause, an owner/manager can retry a failed inbox item. Orders that pass validation appear in the existing online-order management screen. Staff must confirm, collect payment using the existing POS process and fulfil the order; import does not mark an order paid or create a completed POS sale.

### 6. Production release and acceptance

The feature adds migrations to `catalog` and `storefront`, a signed webhook route on the POS app, and a dedicated `whatsapp_worker` Fly process group. Deploy through the approved production workflow; the POS release applies migrations before the new POS app and worker receive traffic.

Before enabling the Meta catalogue sync checkbox in production, complete a controlled acceptance test:
1. Complete Meta coexistence onboarding while the owner is using the existing WhatsApp Business App.
2. Verify the Meta GET webhook challenge and a signed POST webhook.
3. Match one existing catalogue retailer ID to a disposable/approved test SKU.
4. Change its price or stock in POS and confirm Meta reflects the LashPro value.
5. Place a small test cart from WhatsApp. Confirm exactly one WhatsApp order appears in POS and its reservation reduces sellable stock on the website and POS.
6. Cancel the test order or fulfil it through staff workflow and confirm stock is released or deducted exactly once.
7. Send a normal WhatsApp chat message from a client and confirm the owner can still read and reply in the WhatsApp Business App.

Do not enable live imports until the owner has verified the Meta catalogue mapping and the existing POS/storefront shared-Neon database deployment.
