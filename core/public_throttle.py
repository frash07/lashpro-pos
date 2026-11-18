"""Database-backed throttling for public storefront write and lookup endpoints."""

import hashlib
import hmac
import ipaddress
from functools import wraps

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from .models import PublicRateLimitBucket


def _client_address(request):
    # Fly Proxy supplies the client address in Fly-Client-IP. Do not trust an
    # arbitrary X-Forwarded-For value supplied by the browser.
    raw = (request.META.get("HTTP_FLY_CLIENT_IP") or request.META.get("REMOTE_ADDR") or "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "unknown"


def _bucket_hash(request, scope):
    user = getattr(request, "user", None)
    user_id = str(user.pk) if user and user.is_authenticated else "guest"
    material = f"public-rate-limit:v1:{scope}:{_client_address(request)}:{user_id}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), material, hashlib.sha256).hexdigest()


@transaction.atomic
def _consume(scope, key_hash, limit, window_seconds):
    now = timezone.now()
    bucket = PublicRateLimitBucket.objects.select_for_update().filter(pk=key_hash).first()
    if bucket is None:
        try:
            with transaction.atomic():
                bucket = PublicRateLimitBucket.objects.create(
                    key_hash=key_hash,
                    scope=scope,
                    window_started_at=now,
                    request_count=0,
                )
        except IntegrityError:
            # A concurrent first request inserted the unique key first.
            bucket = PublicRateLimitBucket.objects.select_for_update().get(pk=key_hash)

    elapsed = (now - bucket.window_started_at).total_seconds()
    if elapsed >= window_seconds:
        bucket.window_started_at = now
        bucket.request_count = 0

    if bucket.request_count >= limit:
        retry_after = max(1, int(window_seconds - (now - bucket.window_started_at).total_seconds() + 0.999))
        return retry_after

    bucket.request_count += 1
    bucket.save(update_fields=("window_started_at", "request_count", "updated_at"))
    return None


def public_rate_limit(scope, *, limits):
    """Apply per-method (max requests, window seconds) limits keyed by client IP.

    The counter lives in PostgreSQL, so limits are shared across Fly Machines and
    worker processes. Only a keyed digest is stored; raw client IPs are not saved.
    """
    def decorate(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            policy = limits.get(request.method)
            if policy:
                limit, window_seconds = policy
                retry_after = _consume(scope, _bucket_hash(request, scope), limit, window_seconds)
                if retry_after is not None:
                    if "application/json" in request.headers.get("Accept", ""):
                        response = JsonResponse(
                            {"error": "Too many requests. Please try again shortly."},
                            status=429,
                        )
                    else:
                        response = HttpResponse(
                            "Too many requests. Please try again shortly.",
                            status=429,
                        )
                    response["Retry-After"] = str(retry_after)
                    response["Cache-Control"] = "no-store"
                    return response
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorate
