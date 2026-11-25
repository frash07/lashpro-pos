# Storefront M-Pesa STK Push

Online checkout reuses the existing Daraja credentials and callback endpoint on the POS HTTPS origin. The POS and storefront must share the same database and SECRET_KEY (integration settings are encrypted). No credentials belong in Git.

## Rollout

1. Deploy the POS release first (runs migrations); deploy the storefront from the same commit. Leave STOREFRONT_MPESA_ENABLED off until deployment and tests are verified.
2. In Admin Suite → API Integrations configure production consumer key, consumer secret, shortcode, Lipa Na M-Pesa passkey, transaction type (Paybill or Buy Goods), and Party B where appropriate. Verify the existing POS callback is reachable. Do not use sandbox credentials against real orders.
3. Set the Fly storefront secret: `fly secrets set STOREFRONT_MPESA_ENABLED=true -a lashpro-storefront`. No additional credentials are required if the shared POS configuration already works. Verify on a controlled low-value order with the authorized payer's consent.
4. Disable with `fly secrets set STOREFRONT_MPESA_ENABLED=false -a lashpro-storefront`. Existing callbacks still process.

## Workflow

Checkout creates an unpaid order and stock reservation, initiates a prompt for the server-calculated whole-KSh total and customer phone, then redirects to the private order page. The customer can check status and retry a definitively failed attempt only. A pending/unknown outcome blocks additional attempts. Per-IP and per-phone throttles limit abuse.

A validated callback confirms the payment and confirms the order if its reservation remains valid. Staff mark it ready, then fulfil; fulfilment creates the POS sale and allocates the already-confirmed payment in the same transaction. No additional payment is due. No stock is deducted until fulfilment.

Late callbacks on expired orders retain payment and receipt for staff review, without resurrecting released stock. Paid and unresolved orders cannot be cancelled using ordinary staff actions. Managers must resolve late payments/refunds manually (no automatic refund or STK query/reconciliation feature is introduced here). Confirmed funds should be reconciled in the online order register until fulfilment posts them to the POS sale.

## Verification

Run `python manage.py makemigrations --check --dry-run` and `python manage.py test storefront payments`. Test successful callbacks, duplicate submissions, declined/cancelled prompts, amount/phone mismatch, lost responses, late callbacks and fulfilment. Review the public privacy, terms and refunds copy before enabling live checkout.
