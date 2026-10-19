import hashlib
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET


@login_required(login_url="login")
def home(request):
    if getattr(request.user, "role", None) == "TRAINER" and not request.user.is_superuser:
        return redirect("training:dashboard")
    return redirect("sales:checkout")


@require_GET
def health_check(request):
    """Expose a minimal liveness response for the hosting platform."""
    response = HttpResponse("ok", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def service_worker(request):
    precache_urls = [
        static("sales/checkout.css"),
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
