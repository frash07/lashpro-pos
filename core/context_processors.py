def admin_inventory_summary(request):
    """Show a small, read-only low-stock alert on the Django admin home page."""
    if (
        request.path.rstrip("/") != "/admin"
        or not getattr(request, "user", None)
        or not request.user.is_authenticated
        or not request.user.is_staff
    ):
        return {}

    from django.db.models import F
    from catalog.models import Product

    low_stock = Product.objects.filter(
        active=True,
        reorder_level__gt=0,
        on_hand__lte=F("reorder_level"),
    ).order_by("on_hand", "name")
    return {
        "admin_low_stock_count": low_stock.count(),
        "admin_low_stock_products": low_stock[:8],
    }
