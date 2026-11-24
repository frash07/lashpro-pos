# Appointments and provider availability

Appointments are available from the public storefront at `https://lashproke.cc/appointments/` (the path is also registered on the POS host). The booking flow supports guest checkout and signed-in storefront customers. All dates and displayed times use the configured Django timezone (`Africa/Nairobi` in production). The storefront service cards link directly to the selected service's booking page; the page must not be advertised as available until live services and provider hours have been published.

## Publish bookable services

1. Open **Catalog → Services** in Django Admin.
2. Add each customer-facing treatment with its approved name, public price and duration.
3. Leave **Active** enabled for services that should appear on the storefront and booking form. Inactive services remain hidden from customers.
4. Use the real studio price list; do not publish the synthetic test services or sample prices from the test-data command.

## Publish provider hours

1. Sign in to the staff POS account, then open Django Admin at `/admin/`.
2. Open **Appointments → Staff availabilities**.
3. Add one weekly availability row for each provider and working day. Choose an owner, manager, technician or trainer account, weekday, opening time and closing time.
4. A missing row or an inactive row means that provider is not bookable that day. The first release supports one continuous working window per provider per weekday.
5. Add **Staff time offs** for leave, breaks that span a meaningful block, training, or other exceptions. The time-off window is excluded from public availability.

The public booking calendar offers start times in 15-minute increments, for dates from today through 60 days ahead. A service must be active in the catalogue, and its configured duration must fit entirely within the provider's working window.

## Shared database for the POS and storefront

The POS and storefront run as separate Fly.io applications but must use the same production PostgreSQL database (the same `DATABASE_URL`). The public catalogue, appointments, staff accounts and weekly availability are all read from that database. If a service appears in POS Admin but not on the storefront, first verify that both Fly apps have the same database host and database name in their `DATABASE_URL` secret. Do not point either pilot app at the isolated preview or synthetic-test database.

The Admin dashboard includes direct links to the service catalogue, weekly staff availability and staff time off. The booking form is intentionally unavailable until at least one service is active; published provider hours are then required for appointment slots to appear.

## Verify the live booking journey

After the same reviewed application revision is running on both Fly apps:

1. Open `https://lashproke.cc/appointments/` and confirm the page loads over HTTPS.
2. Confirm each active service card's **Book now** link opens the booking page with that service preselected.
3. Pick a date and confirm that published provider slots appear in East Africa Time.
4. Submit a disposable guest request. Confirm the private reference page opens and the request appears in staff appointment management as **Awaiting confirmation**.
5. Confirm the booking is visible in the POS. Cancel the disposable request and verify that its slot becomes available again.
6. Test the availability endpoint at `/appointments/availability/?service=<service-id>&date=<YYYY-MM-DD>`; it must return only currently available slots.

A working URL alone does not establish booking readiness. At least one active service and one active weekly availability row for an eligible provider are required for slots to appear. If there are no slots, check service activation, provider role/activity, weekday, opening/closing times, time off and existing bookings before changing code.

## Booking workflow

- Customers can book as guests or sign in to link appointments to their customer account.
- A new booking is saved as **Awaiting confirmation** and blocks that provider's time immediately for 30 minutes by default (`PUBLIC_BOOKING_HOLD_MINUTES`).
- Owners and managers can confirm or cancel requests from `/appointments/manage/` or Django Admin.
- Assigned providers can mark their own bookings completed or no-show from the staff schedule.
- A customer can cancel from **My appointments** until 24 hours before the start time.
- Cancelled bookings release the slot. Unconfirmed requests that pass their hold deadline become **Expired** and release the slot automatically; confirmed bookings continue to block overlapping times.

The booking transaction locks the selected provider row and rechecks the slot before saving, preventing concurrent storefront requests from assigning the same provider to overlapping appointments. Appointment service name, duration and price are snapshotted at booking time.

## Payment and POS boundary

An appointment request is not a completed sale. This release does not collect deposits or payments, create POS sales, or deduct stock. Best-effort email, SMS and WhatsApp notifications are supported for requested, confirmed, cancelled and expired bookings when providers are configured. See [INTEGRATIONS.md](INTEGRATIONS.md). Payment collection remains a separate staff POS action.
