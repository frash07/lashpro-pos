import uuid
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

from catalog.models import Service


phone_validator = RegexValidator(
    regex=r"^[0-9+()\-\s]{7,20}$",
    message="Enter a valid phone number, including country code if needed.",
)


class AppointmentBookingForm(forms.Form):
    service = forms.ModelChoiceField(
        queryset=Service.objects.none(),
        empty_label="Choose a service",
    )
    appointment_date = forms.DateField(
        label="Appointment date",
        widget=forms.DateInput(
            attrs={"type": "date"},
            format="%Y-%m-%d",
        ),
    )
    slot = forms.ChoiceField(
        label="Available time",
        choices=(),
        widget=forms.Select(),
    )
    full_name = forms.CharField(max_length=100, label="Full name")
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(max_length=20, validators=[phone_validator])
    notes = forms.CharField(
        max_length=500,
        required=False,
        label="Notes (optional)",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    accept_terms = forms.BooleanField(
        required=True,
        label="I agree to the Terms of Service and Returns Policy.",
        error_messages={"required": "You must agree to the Terms of Service and Returns Policy."},
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(active=True).order_by("name")

    def clean_appointment_date(self):
        selected = self.cleaned_data["appointment_date"]
        today = timezone.localdate()
        if selected < today:
            raise ValidationError("Choose today or a future date.")
        if selected > today + timedelta(days=60):
            raise ValidationError("Appointments can be booked up to 60 days ahead.")
        return selected

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

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("idempotency_key"):
            cleaned["idempotency_key"] = uuid.uuid4()
        return cleaned
