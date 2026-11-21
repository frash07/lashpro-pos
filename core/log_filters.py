import logging
import re


_SENSITIVE_PATTERNS = (
    (
        re.compile(r"(?i)(/accounts/password-reset/)[^/?#\s]+/[^/?#\s]+"),
        r"\1<redacted>/<redacted>",
    ),
    (re.compile(r"(?i)(/sales/r/)[^/?#\s]+"), r"\1<redacted>"),
    (
        re.compile(
            r"(?i)([?&](?:token|password|reference|mpesa_reference|secret|api_key|"
            r"session|sessionid|session_token)=)[^&#\s]+"
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(
            r"(?i)\b(?:DATABASE_URL|EMAIL_HOST_PASSWORD|DJANGO_SECRET_KEY|"
            r"DJANGO_BOOTSTRAP_OWNER_(?:PASSWORD|USERNAME|EMAIL)|SYNTHETIC_STAFF_PASSWORD)"
            r"\s*=\s*[^\s,;]+"
        ),
        "<redacted-secret-setting>",
    ),
    (
        re.compile(
            r"(?i)\b(?:password|token|secret|api[_-]?key|client_secret|"
            r"reference|mpesa_reference|sessionid)\s*[:=]\s*[^\s,;&]+"
        ),
        "<redacted-sensitive-value>",
    ),
    (
        re.compile(r"""(?i)\b(?:postgres(?:ql)?|mysql|redis|smtp)://[^\s'"<>]+"""),
        "<redacted-connection-url>",
    ),
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "Bearer <redacted>"),
)


class RedactSensitiveDataFilter(logging.Filter):
    """Remove bearer URLs, credentials, and secret values from log messages."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True

        redacted_message = message
        for pattern, replacement in _SENSITIVE_PATTERNS:
            redacted_message = pattern.sub(replacement, redacted_message)

        if redacted_message != message:
            record.msg = redacted_message
            record.args = ()
        return True
