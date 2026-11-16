# Online orders and inventory

The public storefront checkout now reserves product stock immediately. A reservation reduces the quantity available to both other online customers and the staff POS, but does not change physical on-hand stock until the order is fulfilled.

## Customer flow

1. A customer adds active products to the storefront bag.
2. Checkout rechecks prices and available stock inside a transaction, locks the affected product rows, creates the order and reserves each order line.
3. The customer receives a private order link and can see the current order status.
4. The order remains unpaid. Payment is still collected at the studio; this feature does not integrate a payment gateway or create a paid POS sale.

Reservations are per order line, idempotent with checkout, and use stable product-row locking. An online reservation is included in available-stock calculations and is protected from ordinary POS product sales, service consumable deductions, and stock adjustments that would reduce physical stock below the reserved quantity.

## Staff workflow

Staff process orders from **Django Admin → Storefront orders**. Select orders and use the action matching their current state:

- **Confirm selected online orders**: PLACED → CONFIRMED.
- **Mark selected orders ready for collection**: CONFIRMED → READY.
- **Fulfil selected orders and deduct reserved stock**: READY → FULFILLED.
- **Cancel selected orders and release reserved stock**: PLACED, CONFIRMED or READY → CANCELLED.

Only active owners, managers and cashiers can process orders. The status field is read-only; transitions go through the transactional service so stock cannot be released or deducted by a direct admin edit.

On fulfilment, the system deducts physical on-hand quantity, changes the reservation to consumed, writes one immutable ONLINE_ORDER inventory movement per order line, and records the stock deduction in the audit log. A database one-to-one relation prevents a second online fulfilment movement for the same order line. Cancellation releases active reservations without changing physical stock.

## Inventory and POS boundaries

- Product on-hand is physical stock. Available stock is on_hand minus active online reservations.
- Regular POS product sales and service consumable deductions can use only unreserved stock.
- Stock adjustments cannot reduce physical on-hand below current active reservations. Supplier receipts increase physical stock and therefore increase available stock.
- Fulfilment deducts inventory but does not create a POS sale or payment. The order's payment method remains Pay at studio. Do not create a second POS product sale for the same fulfilled order, because that would represent a second stock issue. Payment/revenue reconciliation against online orders is not included in this release and remains a separate workflow to define.
- Existing orders created before this release have no reservation rows. When staff confirm or mark such an order ready, the workflow attempts to reserve its lines against current available stock and refuses the transition if stock is insufficient.

## Deployment

The release adds:
- storefront.0002_stock_reservations
- inventory.0005_online_order_movements

Deploy with the normal release.sh command so both migrations run before the web machine is updated. No new environment variables or external payment credentials are required.
