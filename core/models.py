import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=50, default="Africa/Nairobi")
    currency = models.CharField(max_length=10, default="KES")
    receipt_prefix = models.CharField(max_length=20, default="LP")


class BusinessSettings(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE)
    opening_time = models.TimeField()
    closing_time = models.TimeField()
    default_commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=40.00
    )


class IntegrationSettings(models.Model):
    """Singleton store for encrypted third-party integration credentials."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    encrypted_config = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_integration_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "API and integration settings"
        verbose_name_plural = "API and integration settings"

    @staticmethod
    def _cipher():
        # Derive a Fernet key from Django's deployment secret; credentials are
        # encrypted before they ever reach the database.
        digest = hashlib.sha256(
            ("lashpro-integration-settings-v1:" + settings.SECRET_KEY).encode("utf-8")
        ).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def get_config(self):
        if not self.encrypted_config:
            return {}
        try:
            cleartext = self._cipher().decrypt(self.encrypted_config.encode("ascii"))
            value = json.loads(cleartext.decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Integration credentials could not be decrypted. Check that the deployment SECRET_KEY has not changed."
            ) from exc
        return value if isinstance(value, dict) else {}

    def set_config(self, value):
        cleartext = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.encrypted_config = self._cipher().encrypt(cleartext).decode("ascii")

    @classmethod
    def get_solo(cls):
        return cls.objects.get_or_create(id=1)[0]

    def __str__(self):
        return "LashPro API and integration settings"


class PublicRateLimitBucket(models.Model):
    """Shared database-backed request counter; stores only an HMAC of the client key."""

    key_hash = models.CharField(max_length=64, primary_key=True)
    scope = models.CharField(max_length=48)
    window_started_at = models.DateTimeField()
    request_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=("updated_at",), name="core_rate_bucket_age_idx")]

