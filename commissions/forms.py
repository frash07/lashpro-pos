from decimal import Decimal
from django import forms
from accounts.models import User
from .models import CommissionPayoutRequest


class CommissionPayoutForm(forms.Form):
    technician = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    method = forms.ChoiceField(choices=CommissionPayoutRequest.Method.choices)
    reference = forms.CharField(required=False, max_length=50)
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["technician"].queryset = User.objects.filter(role=User.Role.TECHNICIAN, is_active=True).order_by("first_name", "username")
