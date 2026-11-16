# Appointments and provider availability

Appointments are available from the public storefront at `/appointments/`. The booking flow supports guest checkout and signed-in storefront customers. All dates and displayed times use the configured Django timezone (`Africa/Nairobi` in production).

## Publish provider hours

1. Sign in to the staff POS account, then open Django Admin at `/admin/`.
2. Open **Appointments → Staff availabilities**.
3. Add one weekly availability row for each provider and working day. Choose an owner, manager, technician or trainer account, weekday, opening time and closing time.
4. A missing row or an inactive row means that provider is not bookable that day. The first release supports one continuous working window per provider per weekday.
5. Add **Staff time offs** for leave, breaks that span a meaningful block, training, or other exceptions. The time-off window is excluded from public availability.

The public booking calendar offers start times in 15-minute increments, for dates from today through 60 days ahead. A service must be active in the catalogue, and its configured duration must fit entirely within the provider's working window.

## Booking workflow

- Customers can book as guests or sign in to link appointments to their customer account.
- A new booking is saved as **Awaiting confirmation** and blocks that provider's time immediately.
- Owners and managers can confirm or cancel requests from `/appointments/manage/` or Django Admin.
- Assigned providers can mark their own bookings completed or no-show from the staff schedule.
- A customer can cancel from **My appointments** until 24 hours before the start time.
- Cancelled bookings release the slot. Requested and confirmed bookings block overlapping times.

The booking transaction locks the selected provider row and rechecks the slot before saving, preventing concurrent storefront requests from assigning the same provider to overlapping appointments. Appointment service name, duration and price are snapshotted at booking time.

## Payment and POS boundary

An appointment request is not a completed sale. This release does not collect deposits or payments, create POS sales, deduct stock, or send SMS/email notifications. Payment collection remains a separate staff POS action.
