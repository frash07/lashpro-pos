# Public-site abuse controls

## Request throttling

Public endpoints use a PostgreSQL-backed fixed-window throttle. Counters are shared across app processes and Fly Machines; they are not held in per-process memory. The database stores an HMAC digest of the key rather than a raw IP address. The client address comes from Fly Proxy's `Fly-Client-IP` header, with `REMOTE_ADDR` as the local/non-Fly fallback.

| Endpoint | Limit |
|---|---:|
| Storefront checkout GET | 60 requests / minute / IP |
| Storefront checkout POST | 5 submissions / 15 minutes / IP |
| Customer registration POST | 3 registrations / hour / IP |
| Appointment booking GET | 60 requests / minute / IP |
| Appointment booking POST | 5 submissions / 15 minutes / IP |
| Appointment availability GET | 60 requests / minute / IP |

A rejected request receives HTTP 429 and a `Retry-After` header. Customer login remains protected by django-axes. These controls throttle abusive traffic; they are not a CAPTCHA and cannot fully prevent a distributed botnet that rotates source IPs.

## Reservation deadlines

- Unconfirmed online orders (PLACED) reserve inventory for 30 minutes by default. Set `PUBLIC_ORDER_RESERVATION_MINUTES` to change the hold duration.
- Unconfirmed appointment requests (REQUESTED) hold a provider's slot for 30 minutes by default. Set `PUBLIC_BOOKING_HOLD_MINUTES` to change it.
- A hold deadline is saved on each record at creation. When it passes, an unconfirmed order no longer counts in stock calculations and an unconfirmed appointment no longer blocks provider availability, even before cleanup writes the EXPIRED status.
- Confirmed/ready orders and confirmed appointments are not subject to the public hold timeout.

Expired orders transition to EXPIRED and their ACTIVE stock reservations are marked RELEASED. Expired appointment requests transition to EXPIRED and trigger best-effort email/SMS/WhatsApp notifications (WhatsApp requires an approved `whatsapp_template_expired` configured with the provider).

## Cleanup command

Run this command once to materialise due expirations and prune old throttle buckets:

```bash
python manage.py expire_public_reservations
```

The dedicated POS `scheduler` process in `fly.toml` runs `scripts/reservation_scheduler.sh` approximately every minute. Scale it to one running Machine and verify logs after deployment. The deadlines themselves are enforced in availability queries and stock calculations, so a delayed cleanup run does not let an expired hold continue to block inventory or a provider slot. The scheduled command updates visible order/appointment statuses and sends booking-expiry notifications.

## Deployment

The new migrations are `core.0003_publicratelimitbucket`, `storefront.0004_public_reservation_expiry` and `appointments.0002_public_booking_expiry`. Deploy with the standard release command so migrations run before the app is updated. Defaults are safe without new Fly secrets; the two hold durations can be overridden with environment variables.
