from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView
from core.views import service_worker
urlpatterns = [
    path("sw.js", service_worker, name="service_worker"),
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(
        template_name="registration/login.html", next_page=reverse_lazy("sales:checkout")),
        name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("sales/", include("sales.urls")),
    path("payments/", include("payments.urls")),
    path("commissions/", include("commissions.urls")),
    path("inventory/", include("inventory.urls")),
    path("reports/", include("reporting.urls")),
    path("", RedirectView.as_view(pattern_name="sales:checkout", permanent=False)),
]
