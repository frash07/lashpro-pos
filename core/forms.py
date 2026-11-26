from django import forms

from .models import IntegrationSettings


class IntegrationSettingsForm(forms.Form):
    # SMTP / transactional email
    email_host = forms.CharField(max_length=255, required=False, label="SMTP host")
    email_port = forms.IntegerField(min_value=1, max_value=65535, initial=587, required=False, label="SMTP port")
    email_username = forms.CharField(max_length=255, required=False, label="SMTP username")
    email_password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        label="SMTP password / app password",
    )
    email_use_tls = forms.BooleanField(required=False, initial=True, label="Use TLS")
    email_from_email = forms.EmailField(required=False, label="From email address")
    operations_notification_email = forms.EmailField(required=False, label="Booking and order alerts email")
    clear_email_password = forms.BooleanField(required=False, label="Remove saved SMTP password")

    # Africa's Talking SMS
    sms_provider = forms.ChoiceField(
        choices=(("", "Disabled"), ("africastalking", "Africa's Talking")),
        required=False, label="SMS provider",
    )
    sms_username = forms.CharField(max_length=100, required=False, label="Africa's Talking username")
    sms_api_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="SMS API key",
    )
    sms_sender_id = forms.CharField(max_length=30, required=False, label="Sender ID (optional)")
    sms_sandbox = forms.BooleanField(required=False, initial=True, label="Use sandbox")
    clear_sms = forms.BooleanField(required=False, label="Remove saved SMS API key")

    # Meta WhatsApp Cloud API
    whatsapp_access_token = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="WhatsApp access token",
    )
    whatsapp_phone_number_id = forms.CharField(max_length=100, required=False, label="WhatsApp phone number ID")
    whatsapp_business_account_id = forms.CharField(max_length=100, required=False, label="WhatsApp Business Account ID")
    whatsapp_catalog_id = forms.CharField(max_length=100, required=False, label="Meta Commerce catalogue ID")
    whatsapp_app_secret = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="Meta app secret",
    )
    whatsapp_webhook_verify_token = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="Webhook verification token",
    )
    whatsapp_catalog_sync_enabled = forms.BooleanField(
        required=False, initial=False, label="Enable automatic catalogue and stock synchronisation",
    )
    whatsapp_api_version = forms.CharField(max_length=20, required=False, initial="v27.0", label="Graph API version")
    whatsapp_language = forms.CharField(max_length=20, required=False, initial="en", label="Template language")
    whatsapp_template_requested = forms.CharField(max_length=100, required=False, label="Booking request template")
    whatsapp_template_confirmed = forms.CharField(max_length=100, required=False, label="Booking confirmed template")
    whatsapp_template_cancelled = forms.CharField(max_length=100, required=False, label="Booking cancelled template")
    whatsapp_template_expired = forms.CharField(max_length=100, required=False, label="Booking request expired template")
    clear_whatsapp = forms.BooleanField(required=False, label="Remove saved WhatsApp credentials")

    # Safaricom Daraja STK Push
    mpesa_environment = forms.ChoiceField(
        choices=(("sandbox", "Sandbox / test"), ("production", "Live production")),
        required=False, initial="sandbox", label="Daraja environment",
    )
    mpesa_consumer_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="Consumer key",
    )
    mpesa_consumer_secret = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="Consumer secret",
    )
    mpesa_passkey = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="Lipa Na M-Pesa passkey",
    )
    mpesa_shortcode = forms.CharField(max_length=20, required=False, label="Business short code")
    mpesa_c2b_shortcodes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}),
        label="C2B callback shortcodes",
        help_text="Enter each Paybill or Till callback shortcode on a separate line. For a Till, use the shortcode Safaricom says should receive the C2B callback.",
    )
    mpesa_party_b = forms.CharField(max_length=20, required=False, label="Party B (optional)")
    mpesa_transaction_type = forms.ChoiceField(
        choices=(
            ("CustomerPayBillOnline", "PayBill"),
            ("CustomerBuyGoodsOnline", "Buy Goods / Till"),
        ),
        required=False, initial="CustomerPayBillOnline", label="STK transaction type",
    )
    mpesa_account_reference = forms.CharField(max_length=12, required=False, initial="LashPro", label="Account reference")
    mpesa_transaction_description = forms.CharField(max_length=13, required=False, initial="POS Payment", label="Transaction description")
    clear_mpesa = forms.BooleanField(required=False, label="Remove saved Daraja keys and passkey")

    # KRA eTIMS configuration (credentials are stored, activation is gated)
    etims_environment = forms.ChoiceField(
        choices=(("sandbox", "Sandbox / test"), ("production", "Production")),
        required=False, initial="sandbox", label="eTIMS environment",
    )
    etims_api_base_url = forms.URLField(required=False, label="eTIMS API base URL")
    etims_taxpayer_pin = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="KRA taxpayer PIN",
    )
    etims_branch_id = forms.CharField(max_length=50, required=False, label="Branch ID")
    etims_device_serial = forms.CharField(max_length=100, required=False, label="OSCU / VSCU device serial")
    etims_communication_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="KRA-issued communication key",
    )
    clear_etims = forms.BooleanField(required=False, label="Remove saved eTIMS credentials")

    SECRET_FIELDS = {
        "email_password", "sms_api_key", "whatsapp_access_token", "whatsapp_app_secret",
        "whatsapp_webhook_verify_token",
        "mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_passkey", "mpesa_c2b_callback_token",
        "etims_taxpayer_pin", "etims_communication_key",
    }
    CLEAR_GROUPS = {
        "clear_email_password": ("email_password",),
        "clear_sms": ("sms_api_key",),
        "clear_whatsapp": ("whatsapp_access_token", "whatsapp_app_secret", "whatsapp_webhook_verify_token"),
        "clear_mpesa": ("mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_passkey"),
        "clear_etims": ("etims_taxpayer_pin", "etims_communication_key"),
    }

    def __init__(self, *args, settings_record=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings_record = settings_record or IntegrationSettings.get_solo()
        self.existing_config = self.settings_record.get_config()
        for name, field in self.fields.items():
            if name.startswith("clear_") or name in self.SECRET_FIELDS:
                continue
            if name in self.existing_config:
                self.initial[name] = self.existing_config[name]
        self.initial["has_email_password"] = bool(self.existing_config.get("email_password"))
        self.initial["has_sms_api_key"] = bool(self.existing_config.get("sms_api_key"))
        self.initial["has_whatsapp_access_token"] = bool(self.existing_config.get("whatsapp_access_token"))
        self.initial["has_whatsapp_app_secret"] = bool(self.existing_config.get("whatsapp_app_secret"))
        self.initial["has_whatsapp_webhook_token"] = bool(self.existing_config.get("whatsapp_webhook_verify_token"))
        self.initial["has_mpesa_credentials"] = all(
            self.existing_config.get(key)
            for key in ("mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_passkey", "mpesa_shortcode")
        )
        self.initial["has_etims_credentials"] = bool(
            self.existing_config.get("etims_taxpayer_pin")
            and self.existing_config.get("etims_communication_key")
        )

    def merged_config(self):
        config = dict(self.existing_config)
        for name in self.fields:
            if name.startswith("clear_") or name in self.SECRET_FIELDS:
                continue
            config[name] = self.cleaned_data.get(name)
        for clear_flag, keys in self.CLEAR_GROUPS.items():
            if self.cleaned_data.get(clear_flag):
                for key in keys:
                    config.pop(key, None)
        for name in self.SECRET_FIELDS:
            value = (self.cleaned_data.get(name) or "").strip()
            if value:
                config[name] = value
        return config
