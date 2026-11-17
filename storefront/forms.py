import uuid

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from accounts.models import User
from .models import StorefrontProfile


phone_validator = RegexValidator(
    regex=r"^[0-9+()\-\s]{7,20}$",
    message="Enter a valid phone number, including country code if needed.",
)


class CustomerRegistrationForm(forms.Form):
    full_name = forms.CharField(max_length=100, label="Full name")
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=20, validators=[phone_validator])
    accept_terms = forms.BooleanField(
        required=True,
        label="I agree to the Terms of Service and Returns Policy.",
        error_messages={"required": "You must agree to the Terms of Service and Returns Policy."},
    )
    password1 = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput,
        label="Password",
    )
    password2 = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput,
        label="Confirm password",
    )

    def clean_full_name(self):
        value = " ".join(self.cleaned_data["full_name"].split())
        if len(value) < 2:
            raise ValidationError("Enter your full name.")
        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if StorefrontProfile.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already uses this email. Sign in instead.")
        return email

    def clean_phone(self):
        return self.cleaned_data["phone"].strip()

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        email = cleaned.get("email")
        full_name = cleaned.get("full_name", "")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1 and email:
            parts = full_name.split(maxsplit=1)
            candidate = User(
                username="new-storefront-customer",
                email=email,
                first_name=parts[0] if parts else "",
                last_name=parts[1] if len(parts) > 1 else "",
            )
            try:
                validate_password(password1, user=candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class CustomerLoginForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class StorefrontCheckoutForm(forms.Form):
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)
    full_name = forms.CharField(max_length=100, label="Full name")
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=20, validators=[phone_validator])
    notes = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Collection notes (optional)",
    )
    accept_terms = forms.BooleanField(
        required=True,
        label="I agree to the Terms of Service and Returns Policy.",
        error_messages={"required": "You must agree to the Terms of Service and Returns Policy."},
    )

    def clean_full_name(self):
        value = " ".join(self.cleaned_data["full_name"].split())
        if len(value) < 2:
            raise ValidationError("Enter your full name.")
        return value

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        return self.cleaned_data["phone"].strip()

    def clean_notes(self):
        return self.cleaned_data["notes"].strip()
