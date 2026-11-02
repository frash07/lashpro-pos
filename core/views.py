import hashlib
import json

from django.http import HttpResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@require_GET
def service_worker(request):
    precache_urls = [
        static("css/tokens.css"),
        static("css/components.css"),
        static("css/legacy.css"),
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
    script = '''
const CACHE_NAME = __CACHE_NAME__;
const CACHE_PREFIX = "lashpro-static-";
const PRECACHE_URLS = __PRECACHE_URLS__;
const OFFLINE_URL = __OFFLINE_URL__;
const LOGOUT_PATHS = __LOGOUT_PATHS__;
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
    event.respondWith(fetch(request).catch(async () => {
      const fallback = await caches.match(OFFLINE_URL);
      return fallback || new Response("You are offline. Reconnect to continue.", { headers: { "Content-Type": "text/plain; charset=utf-8" }, status: 503 });
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
    response = HttpResponse(script, content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    response["X-Content-Type-Options"] = "nosniff"
    return response

@staff_member_required
def admin_suite(request):
    groups = [
        {
            "name": "People & Access",
            "description": "User accounts, roles, permissions and sign-in security.",
            "icon": "users",
            "items": [
                ("User Accounts", "/admin/accounts/user/"),
                ("Groups & Permissions", "/admin/auth/"),
                ("Access Attempts", "/admin/axes/accessattempt/"),
                ("Failed Login Records", "/admin/axes/accessfailurelog/"),
                ("Login Activity", "/admin/axes/accesslog/"),
            ],
        },
        {
            "name": "Audit & Compliance",
            "description": "Review the application's recorded audit events.",
            "icon": "shield-check",
            "items": [
                ("Audit Events", "/admin/audit/auditevent/"),
            ],
        },
        {
            "name": "Studio Catalogue",
            "description": "Maintain the retail product and service catalogue.",
            "icon": "package",
            "items": [
                ("Products", "/admin/catalog/product/"),
                ("Services", "/admin/catalog/service/"),
            ],
        },
        {
            "name": "Clients",
            "description": "Manage customer records and client details.",
            "icon": "contact-round",
            "items": [
                ("Customer Directory", "/admin/customers/customer/"),
            ],
        },
        {
            "name": "Inventory & Stock",
            "description": "Inspect stock movements, consumables and adjustment requests.",
            "icon": "boxes",
            "items": [
                ("Inventory Movements", "/admin/inventory/inventorymovement/"),
                ("Service Consumables", "/admin/inventory/serviceconsumable/"),
                ("Stock Adjustment Requests", "/admin/inventory/stockadjustmentrequest/"),
            ],
        },
        {
            "name": "Artist Commissions",
            "description": "Review commission ledger entries and payout records.",
            "icon": "hand-coins",
            "items": [
                ("Commission Ledger Entries", "/admin/commissions/commissionledgerentry/"),
                ("Commission Payout Requests", "/admin/commissions/commissionpayoutrequest/"),
                ("Commission Payout Records", "/admin/commissions/commissionpayoutrecord/"),
            ],
        },
        {
            "name": "Payments & Cash Control",
            "description": "Manage cash sessions, payment records and reconciliations.",
            "icon": "wallet-cards",
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
            "name": "Sales & Refunds",
            "description": "Open sale records, line items and refund records.",
            "icon": "receipt-text",
            "items": [
                ("Sales Records", "/admin/sales/sale/"),
                ("Sale Line Items", "/admin/sales/saleline/"),
                ("Refund Records", "/admin/sales/salerefund/"),
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
