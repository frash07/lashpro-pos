# WhatsApp Business App coexistence and LashPro commerce

This integration is designed to let the owner continue using the existing WhatsApp Business App and phone number while LashPro uses Meta's Cloud API for catalogue updates and inbound catalogue-cart orders.

## Important: preserve the owner's existing number

Do **not** use the normal Cloud API number-migration/registration flow for this rollout. The owner must be onboarded using Meta's WhatsApp Business App coexistence option (also known as onboarding WhatsApp Business App users). Coexistence eligibility is decided by Meta. The owner completes the Meta-controlled consent and number-verification steps on the existing business number.

The coexistence onboarding flow is separate from the webhook and catalogue code in this repository. It must be completed using a Meta app/solution provider configured for WhatsApp Business App coexistence. Meta Embedded Signup apps generally need the relevant business verification, app review and advanced permissions; an approved BSP/Tech Provider that supports coexistence is an alternative. Confirm the exact app permissions and account eligibility in Meta's current developer dashboard before onboarding.

The owner should:
1. Keep the WhatsApp Business App installed and accessible on the primary phone.
2. Start the coexistence onboarding from the approved Meta Embedded Signup/BSP flow.
3. Select the option to connect the **existing WhatsApp Business App number**, not to register a replacement number.
4. Verify the number using the flow shown by Meta and complete the permission prompts.
5. Confirm that the owner can still send and receive ordinary one-to-one chats in the WhatsApp Business App after onboarding.

Do not disconnect the number or switch it to an API-only registration as part of this setup.

## Meta assets and permissions

Create or select the ecommerce product catalogue in Meta Commerce Manager and connect it to the same WhatsApp Business Account used by the existing number.

The access token used by LashPro needs access to the connected catalogue and WhatsApp assets. At minimum, confirm the relevant current permissions for WhatsApp messaging/management and catalogue management (including `catalog_management`). Use a long-lived/system-user token appropriate for the business. Never put the token or Meta app secret in GitHub source, an issue, or a log.

In **POS → Admin Suite → API & Payment Integrations → WhatsApp**, configure:

- **WhatsApp access token** — Meta access token with the required permissions.
- **WhatsApp phone number ID** — the phone-number ID for the existing, coexistence-enabled business number.
- **WhatsApp Business Account ID** — the WABA ID subscribed to the webhook.
- **Meta Commerce catalogue ID** — the product catalogue connected to that WABA.
- **Meta app secret** — used to verify the `X-Hub-Signature-256` webhook signature.
- **Webhook verification token** — a long, random secret created by the operator. Enter the same value in Meta's webhook subscription verification screen.
- **Graph API version** — use a supported Meta Graph API version.
- **Automatic catalogue and stock synchronisation** — enable only after checking the catalogue ID and the initial SKU mapping.

The app secret and webhook verification token are encrypted in LashPro's integration settings. They are never rendered back to the settings page.

## Webhook configuration

Use the callback URL displayed on the integration settings page. The production POS callback is:

`https://lashpro-pos.fly.dev/webhooks/whatsapp/`

Configure Meta Webhooks for the correct WhatsApp Business Account and subscribe to the `messages` field. Use the exact same webhook verification token saved in LashPro. Meta's signed POST events are checked using the app secret before any order is processed.

Only messages of WhatsApp message type `order` (a customer-submitted catalogue cart) are imported. Ordinary chat messages, text enquiries, images and order-status echoes are not converted into sales automatically.

## Product mapping and catalogue updates

LashPro maps the Meta catalogue `retailer_id` (shown as Content ID in Commerce Manager) to each product. In **POS → Catalog → Products**, use **WhatsApp retailer ID** to map an existing Meta Content ID when it differs from the POS SKU. If this field is blank, LashPro uses the POS SKU as the Meta retailer ID. The mapping becomes read-only after the product is added to the sync queue so the connected catalogue item ID remains stable. Before the first full sync:

1. Confirm each POS SKU is correct and permanent.
2. For each product already in the Meta catalogue, copy its Content ID into the POS product's WhatsApp retailer ID field. This avoids publishing a duplicate item or changing the POS SKU.
3. Upload a public product image to each product. Meta requires a public image URL when the catalogue item is first published.
4. Confirm the selling price in the POS is correct and in KES.
5. Connect the correct catalogue to the WABA and enable automatic sync in the integration settings.

Product create/update and stock-reservation changes queue an outbox update in Neon. A scheduled GitHub Actions workflow runs the POS management command every five minutes and publishes pending updates to Meta. Catalogue item price, inventory count and in-stock/out-of-stock state are derived from the Neon price and **unreserved available stock**. Inactive products are staged/discontinued.

The workflow needs the GitHub repository secret `FLY_POS_API_TOKEN` with access to the `lashpro-pos` Fly app. The workflow is `.github/workflows/whatsapp-catalog-sync.yml`. It supports a manual full reconciliation with `full_sync=true`. Failed items remain visible under Django Admin → WhatsApp catalogue sync and can be retried there.

Manual alternatives from an authenticated Fly session:

```bash
fly ssh console --app lashpro-pos -C "python manage.py sync_whatsapp_catalog"
fly ssh console --app lashpro-pos -C "python manage.py sync_whatsapp_catalog --all-products"
```

A failed Meta API call does not block a POS checkout, stock movement or online order. It remains in the retry queue with an error for staff review.

## WhatsApp orders and stock safety

When a customer submits a catalogue cart:

- LashPro identifies each item by Meta `product_retailer_id`, which must match a current active POS SKU.
- Neon is authoritative for the product name, selling price and available stock. The price supplied by the WhatsApp order is not used to create the LashPro order.
- A successful cart is imported as a normal online order with source **WhatsApp catalogue** and status **Awaiting staff confirmation**.
- The normal online-order reservation engine locks product rows and reserves available stock. The default reservation expires after the configured public order hold period (30 minutes unless changed).
- The order appears in Django Admin → Storefront orders / Online Orders and can be confirmed, marked ready, fulfilled, or cancelled using the existing staff workflow.
- When staff fulfils the order, LashPro consumes the stock and creates/links the POS sale using the existing online-order flow. No payment is recorded merely because a WhatsApp cart was received.

Orders with unknown/inactive SKUs, invalid quantities or insufficient stock are recorded under Django Admin → WhatsApp inbound orders with **Needs staff review**. They do not reserve stock or become POS sales. A repeated Meta webhook delivery is idempotent and cannot create a second order.

## Rollout checks

Use a controlled test product and a test customer before accepting live WhatsApp orders:

1. Verify the owner can still chat from the WhatsApp Business App using the existing number.
2. Confirm Meta webhook verification succeeds and a signed test event reaches LashPro.
3. Run a full catalogue sync and verify the expected SKUs, prices, images and stock state in Commerce Manager and the WhatsApp catalogue.
4. Submit a real test catalogue cart with one test SKU and verify one WhatsApp-sourced order appears in LashPro.
5. Confirm unreserved stock decreases immediately in Neon, the website and POS availability views.
6. Confirm a duplicate webhook event does not create a second order.
7. Confirm insufficient-stock and unknown-SKU orders are sent to the staff review list.
8. Fulfil a test order through the existing staff flow and verify the final stock movement and POS sale.

A catalogue link by itself does not prove that Cloud API coexistence, webhook subscriptions or product synchronisation are configured. Do not announce that WhatsApp orders are automatically connected until these checks pass.
