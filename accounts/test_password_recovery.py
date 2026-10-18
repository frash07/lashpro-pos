from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch


User = get_user_model()


class PasswordRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resettable",
            password="Original-test-password!4",
            email="resettable@example.com",
        )

    def test_login_page_links_to_password_reset(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("password_reset"))

    @override_settings(
        EMAIL_HOST="",
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    )
    def test_reset_does_not_emit_sensitive_link_into_console_logs_when_email_missing(self):
        with patch("django.core.mail.message.EmailMultiAlternatives.send") as send:
            response = self.client.post(
                reverse("password_reset"),
                {"email": self.user.email},
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password recovery email is not configured")
        send.assert_not_called()

    @override_settings(
        EMAIL_HOST="smtp.test.example",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="LashPro Test <noreply@example.com>",
    )
    def test_configured_email_reset_sends_link(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/password-reset/", mail.outbox[0].body)

    def test_authenticated_user_can_change_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "Original-test-password!4",
                "new_password1": "New-Strong-Password!9857",
                "new_password2": "New-Strong-Password!9857",
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-Strong-Password!9857"))
