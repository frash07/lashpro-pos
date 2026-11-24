import hashlib
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.db import connection, DatabaseError
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.shortcuts import redirect, render

from accounts.models import User
from .forms import IntegrationSettingsForm
from .models import IntegrationSettings


@login_required(login_url="login")
def home(request):
    if request.user.role == User.Role.TRAINER and not request.user.is_superuser:
        return redirect("training:dashboard")
    if request.user.role == User.Role.TECHNICIAN:
        return redirect("sales:services")
    return redirect("sales:checkout")


@require_GET
def health_check(request):
    """Expose a minimal liveness response for the hosting platform."""
    response = HttpResponse("ok", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def readiness_check(request):
    """Check database connectivity without exposing internal configuration."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        response = HttpResponse("unavailable", status=503, content_type="text/plain; charset=utf-8")
    else:
        response = HttpResponse("ok", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def service_worker(request):
    precache_urls = [
        static("css/tokens.css"),
        static("css/components.css"),
        static("css/pos.css"),
        static("css/auth.css"),
        static("css/admin-shell.css"),
        static("css/receipt.css"),
        static("js/pos.js"),
        static("img/logo-lashpro.svg"),
        static("img/product-placeholder.svg"),
        static("pwa/favicon-32.png"),
        static("pwa/favicon-48.png"),
        static("pwa/icon-180.png"),
        static("pwa/icon-192.png"),
        static("pwa/icon-512.png"),
        static("pwa/icon-maskable-512.png"),
        static("pwa/offline.html"),
    ]
    cache_name = "lashpro-static-" + hashlib.sha256(json.dumps(precache_urls).encode("utf-8")).hexdigest()[:12]
    logout_paths = [reverse("logout"), reverse("admin:logout")]
    checkout_path = reverse("sales:checkout")
    script = '''
const CACHE_NAME = __CACHE_NAME__;
const CACHE_PREFIX = "lashpro-static-";
const PRECACHE_URLS = __PRECACHE_URLS__;
const OFFLINE_URL = __OFFLINE_URL__;
const LOGOUT_PATHS = __LOGOUT_PATHS__;
const CHECKOUT_PATH = __CHECKOUT_PATH__;
const PRECACHE_PATHS = new Set(PRECACHE_URLS.map((path) => new URL(path, self.location.origin).pathname));

async function clearLashProCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX)).map((key) => caches.delete(key)));
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(PRECACHE_URLS);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (LOGOUT_PATHS.includes(url.pathname)) event.waitUntil(clearLashProCaches());
  if (request.method !== "GET") {
    event.respondWith(fetch(request).catch(() => {
      const checkoutFailed = request.method === "POST" && url.pathname === CHECKOUT_PATH;
      const heading = checkoutFailed ? "Checkout status unknown" : "Request status unknown";
      const guidance = checkoutFailed
        ? "Check Sales before retrying. Do not start a new sale or payment until you have checked whether this checkout was recorded."
        : "The server may have received this request before the connection was lost. Check the relevant record before retrying.";
      const html = `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${heading} · LashPro</title></head>
<body style="font-family:system-ui,sans-serif;max-width:42rem;margin:10vh auto;padding:1.5rem;line-height:1.55;color:#241b23">
  <main role="alert">
    <h1>${heading}</h1>
    <p>${guidance}</p>
    <p>Your checkout details are retained in this tab. Return to the POS only after checking the Sales register.</p>
  </main>
</body>
</html>`;
      return new Response(html, {
        status: 503,
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff"
        }
      });
    }));
    return;
  }

  if (PRECACHE_PATHS.has(url.pathname)) {
    event.respondWith(caches.open(CACHE_NAME).then((cache) => cache.match(request).then((cached) => cached || fetch(request))));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(async () => {
      const fallback = await caches.match(OFFLINE_URL);
      return fallback || new Response("You are offline. Reconnect to continue.", { headers: { "Content-Type": "text/plain; charset=utf-8" }, status: 503 });
    }));
  }
});
'''
    script = script.replace("__CACHE_NAME__", json.dumps(cache_name))
    script = script.replace("__PRECACHE_URLS__", json.dumps(precache_urls))
    script = script.replace("__OFFLINE_URL__", json.dumps(static("pwa/offline.html")))
    script = script.replace("__LOGOUT_PATHS__", json.dumps(logout_paths))
    script = script.replace("__CHECKOUT_PATH__", json.dumps(checkout_path))
    response = HttpResponse(script, content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    response["X-Content-Type-Options"] = "nosniff"
    return response

@staff_member_required
def admin_suite(request):
    from django.core.exceptions import PermissionDenied
    from accounts.models import User

    if not (
        request.user.is_superuser
        or (
            request.user.is_staff
            and getattr(request.user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}
        )
    ):
        raise PermissionDenied

    groups = [
        {
            "name": "People & Access",
            "description": "User accounts, roles, audit events and sign-in security.",
            "icon": "users",
            "items": [
                ("User Accounts", "/admin/accounts/user/"),
                ("Roles & Permissions", "/admin/auth/"),
                ("Audit Events", "/admin/audit/auditevent/"),
                ("Access Attempts", "/admin/axes/accessattempt/"),
                ("Failed Login Records", "/admin/axes/accessfailurelog/"),
                ("Login Activity", "/admin/axes/accesslog/"),
            ],
        },
        {
            "name": "Catalog",
            "description": "Maintain the retail product and service catalogue.",
            "icon": "package",
            "items": [
                ("Products", "/admin/catalog/product/"),
                ("Services", "/admin/catalog/service/"),
            ],
        },
        {
            "name": "Customers",
            "description": "Manage customer records and client details.",
            "icon": "contact-round",
            "items": [
                ("Customer Directory", "/admin/customers/customer/"),
            ],
        },
        {
            "name": "Sales",
            "description": "Open sale records, line items and refund records.",
            "icon": "receipt-text",
            "items": [
                ("Sales Records", "/admin/sales/sale/"),
                ("Online Store Orders", "/admin/storefront/storefrontorder/"),
                ("Sale Line Items", "/admin/sales/saleline/"),
                ("Refund Records", "/admin/sales/salerefund/"),
            ],
        },
        {
            "name": "Inventory",
            "description": "Inspect stock movements, consumables and adjustment requests.",
            "icon": "warehouse",
            "items": [
                ("Inventory Movements", "/admin/inventory/inventorymovement/"),
                ("Service Consumables", "/admin/inventory/serviceconsumable/"),
                ("Stock Adjustment Requests", "/admin/inventory/stockadjustmentrequest/"),
            ],
        },
        {
            "name": "Payments & Cash",
            "description": "Manage cash sessions, payment records and reconciliations.",
            "icon": "wallet",
            "items": [
                ("Cash Sessions", "/admin/payments/cashsession/"),
                ("Cash Session Movements", "/admin/payments/cashsessionmovement/"),
                ("Payment Reconciliation", "/admin/payments/paymentreconciliation/"),
                ("Payment Transactions", "/admin/payments/paymenttransaction/"),
                ("Payout Reconciliation", "/admin/payments/payoutreconciliation/"),
                ("Refund Payouts", "/admin/payments/refundpayout/"),
                ("Sale Payments", "/admin/payments/salepayment/"),
            ],
        },
        {
            "name": "Expenses",
            "description": "Record operating costs, track outstanding bills and review the expense audit trail.",
            "icon": "receipt",
            "items": [
                ("Expense Register", "/expenses/"),
                ("Expense Records", "/admin/expenses/expense/"),
            ],
        },
        {
            "name": "Artist Commissions",
            "description": "Review commission ledger entries and payout records.",
            "icon": "badge-dollar-sign",
            "items": [
                ("Commission Ledger Entries", "/admin/commissions/commissionledgerentry/"),
                ("Commission Payout Records", "/admin/commissions/commissionpayoutrecord/"),
                ("Commission Payout Requests", "/admin/commissions/commissionpayoutrequest/"),
            ],
        },
        {
            "name": "Communications & Integrations",
            "description": "Connect SMS, WhatsApp, email, M-Pesa Daraja and KRA eTIMS credentials.",
            "icon": "plug-zap",
            "items": [
                ("API & Payment Integrations", "/admin-suite/integrations/"),
                ("WhatsApp Inbound Orders", "/admin/storefront/whatsappinboundorder/"),
                ("WhatsApp Catalogue Sync", "/admin/storefront/whatsappcatalogsync/"),
            ],
        },
    ]

    groups = [
        {
            "name": group["name"],
            "description": group["description"],
            "icon": group["icon"],
            "items": [
                {"label": label, "url": url}
                for label, url in group["items"]
            ],
        }
        for group in groups
    ]

    return render(request, "admin_suite/index.html", {"groups": groups})

@staff_member_required
def integration_settings(request):
    from django.core.exceptions import PermissionDenied
    from accounts.models import User

    if not (
        request.user.is_superuser
        or (
            request.user.is_staff
            and getattr(request.user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}
        )
    ):
        raise PermissionDenied

    record = IntegrationSettings.get_solo()
    if request.method == "POST":
        form = IntegrationSettingsForm(request.POST, settings_record=record)
        if form.is_valid():
            record.set_config(form.merged_config())
            record.updated_by = request.user
            record.save(update_fields=("encrypted_config", "updated_by", "updated_at"))
            messages.success(request, "Integration settings saved. Provider credentials are encrypted at rest.")
            return redirect("integrations-settings")
        messages.error(request, "Review the highlighted fields and try again.")
    else:
        form = IntegrationSettingsForm(settings_record=record)

    config = record.get_config()
    return render(request, "core/integrations.html", {
        "form": form,
        "whatsapp_webhook_url": request.build_absolute_uri(reverse("whatsapp_webhook")),
        "config_status": {
            "email": bool(config.get("email_host") and config.get("email_from_email")),
            "email_password": bool(config.get("email_password")),
            "sms": bool(config.get("sms_provider") == "africastalking" and config.get("sms_username") and config.get("sms_api_key")),
            "whatsapp": bool(config.get("whatsapp_access_token") and config.get("whatsapp_phone_number_id")),
            "whatsapp_commerce": bool(all(config.get(key) for key in ("whatsapp_access_token", "whatsapp_phone_number_id", "whatsapp_business_account_id", "whatsapp_catalog_id", "whatsapp_app_secret", "whatsapp_webhook_verify_token"))),
            "whatsapp_catalog_sync": bool(config.get("whatsapp_catalog_sync_enabled") and config.get("whatsapp_access_token") and config.get("whatsapp_catalog_id")),
            "mpesa": bool(all(config.get(key) for key in ("mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_passkey", "mpesa_shortcode"))),
            "etims": bool(config.get("etims_taxpayer_pin") and config.get("etims_communication_key")),
        },
        "updated_at": record.updated_at,
    })

