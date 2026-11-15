from django.conf import settings
from django.db.models import Q
from django.shortcuts import redirect, render

from catalog.models import Product, Service


def home(request):
    """Render the public catalogue, or send the POS hostname to staff checkout."""
    hostname = request.get_host().split(":", 1)[0].lower()
    pos_hosts = {host.lower() for host in getattr(settings, "POS_HOSTS", [])}

    if hostname in pos_hosts:
        return redirect("sales:checkout")

    query = (request.GET.get("q") or "").strip()[:80]
    kind = (request.GET.get("kind") or "all").strip().lower()
    if kind not in {"all", "products", "services"}:
        kind = "all"

    products = Product.objects.filter(active=True).order_by("name")
    services = Service.objects.filter(active=True).order_by("name")

    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query)
        )
        services = services.filter(name__icontains=query)

    if kind == "products":
        services = Service.objects.none()
    elif kind == "services":
        products = Product.objects.none()

    return render(
        request,
        "storefront/home.html",
        {
            "products": products,
            "services": services,
            "query": query,
            "kind": kind,
            "product_count": products.count(),
            "service_count": services.count(),
            "pos_url": settings.POS_BASE_URL,
        },
    )
