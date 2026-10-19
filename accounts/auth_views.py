from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect


class SafePasswordResetView(auth_views.PasswordResetView):
    """Never emit reset URLs into production logs when email is not configured."""

    def form_valid(self, form):
        if (
            not settings.EMAIL_HOST
            or settings.EMAIL_BACKEND.endswith("console.EmailBackend")
        ):
            messages.error(
                self.request,
                "Password recovery email is not configured. Please contact your LashPro manager.",
            )
            return redirect("password_reset")
        return super().form_valid(form)
