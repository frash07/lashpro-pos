from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView
from core.views import service_worker
from accounts.auth_views import SafePasswordResetView
urlpatterns = [
    path("sw.js", service_worker, name="service_worker"),
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(
        template_name="registration/login.html", next_page=reverse_lazy("sales:checkout")),
        name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(
        template_name="registration/password_change_form.html",
        success_url=reverse_lazy("password_change_done"),
    ), name="password_change"),
    path("accounts/password-change/done/", auth_views.PasswordChangeDoneView.as_view(
        template_name="registration/password_change_done.html",
    ), name="password_change_done"),
    path("accounts/password-reset/", SafePasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt",
        success_url=reverse_lazy("password_reset_done"),
    ), name="password_reset"),
    path("accounts/password-reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html",
    ), name="password_reset_done"),
    path("accounts/password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html",
        success_url=reverse_lazy("password_reset_complete"),
    ), name="password_reset_confirm"),
    path("accounts/password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html",
    ), name="password_reset_complete"),
    path("sales/", include("sales.urls")),
    path("payments/", include("payments.urls")),
    path("commissions/", include("commissions.urls")),
    path("inventory/", include("inventory.urls")),
    path("reports/", include("reporting.urls")),
    path("", RedirectView.as_view(pattern_name="sales:checkout", permanent=False)),
]
