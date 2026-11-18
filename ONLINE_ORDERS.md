# Online orders, inventory and POS reconciliation

The public storefront checkout reserves product stock immediately. A reservation reduces the quantity available to both other online customers and the staff POS, but does not change physical on-hand stock until the order is fulfilled. An unconfirmed PLACED order holds stock for 30 minutes by default (`PUBLIC_ORDER_RESERVATION_MINUTES`); after its deadline it no longer counts against available stock and is marked EXPIRED by the cleanup command or the next storefront/admin sweep.

## Customer flow

1. A customer adds active products to the storefront bag.
2. Checkout rechecks prices and available stock inside a transaction, locks the affected product rows, creates the order and reserves each order line.
3. The customer receives a private order link and can see the current order status.
4. The order remains unpaid. Payment is collected at the studio; this feature does not integrate a payment gateway or create a paid POS sale at checkout.

Reservations are per order line, idempotent with checkout, and use stable product-row locking. An online reservation is included in available-stock calculations and is protected from ordinary POS product sales, service consumable deductions, and stock adjustments that would reduce physical stock below the reserved quantity.

## Staff workflow

Staff process orders from **Django Admin → Storefront orders**. Select orders and use the action matching their current state:

- **Confirm selected online orders**: PLACED → CONFIRMED.
- **Mark selected orders ready for collection**: CONFIRMED → READY.
- **Fulfil orders, deduct stock and create POS sales**: READY → FULFILLED.
- **Cancel selected orders and release reserved stock**: PLACED, CONFIRMED or READY → CANCELLED.
- Unconfirmed PLACED orders that pass their reservation deadline automatically become EXPIRED and release stock. Confirmed/ready orders are not subject to the public hold timeout.

Only active owners, managers and cashiers can process orders. The status field is read-only; transitions go through the transactional service so stock cannot be released or deducted by a direct admin edit.

## POS revenue and payment reconciliation

Fulfilling an order performs the stock deduction and creates a linked **completed POS sale** in the same database transaction. The POS sale uses the original order-line descriptions, quantities and captured checkout prices. It appears in completed-sale counts and gross revenue reporting, and the Storefront order admin page shows its receipt reference.

The POS sale does not create a payment automatically. The storefront payment option is **Pay at studio**, so a payment must not be inferred merely because staff marked an order fulfilled. To record money actually received:

1. Open the POS **Collect a sale balance** page from the online order's linked POS sale.
2. Select the actual method and amount. Cash collection requires the collecting staff member to have an open cash session.
3. Record the M-Pesa transaction reference for manual M-Pesa. It remains unverified until an owner or manager reconciles it against the statement.

This keeps gross sales separate from confirmed cash/M-Pesa collections. An unpaid online order therefore appears as revenue after fulfilment but remains in the outstanding POS balance until its payment is entered. A second POS checkout must not be created for the same order: that would duplicate revenue and potentially deduct the stock twice.

On fulfilment, the system deducts physical on-hand quantity, changes the reservation to consumed, writes one immutable ONLINE_ORDER inventory movement per order line, and records the stock deduction in the audit log. The linked POS sale does not run a second product-stock deduction. A database one-to-one relation prevents a second online fulfilment movement for the same order line. Cancellation releases active reservations without changing physical stock.

## Existing fulfilled orders

The migration creates linked POS sales for historical fulfilled orders when the audit log identifies the staff member who fulfilled them. It does not create payments or change inventory. If a legacy order has no matching fulfilment audit event, it is left untouched rather than inventing a cashier; an owner should review that order manually.

Existing orders created before stock reservations were introduced have no reservation rows. When staff confirm or mark such an order ready, the workflow attempts to reserve its lines against current available stock and refuses the transition if stock is insufficient.

## Deployment

The release adds:
- `storefront.0003_storefrontorder_sale`

Deploy with the normal `release.sh` command so the migration runs before the web machine is updated. No new environment variables or external payment credentials are required.
