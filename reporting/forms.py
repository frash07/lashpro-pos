from django import forms
from django.utils import timezone


class ReportDateFilterForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        today = timezone.localdate()
        kwargs.setdefault("initial", {"start_date": today, "end_date": today})
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError("Start date must be on or before end date.")
        return cleaned
