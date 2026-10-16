from decimal import Decimal
from django import forms


class OpenCashSessionForm(forms.Form):
    opening_float = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"), initial=Decimal("0.00"), label="Opening float (KSh)")


class CloseCashSessionForm(forms.Form):
    counted_cash = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"), label="Cash counted (KSh)")
    reason = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 3}), label="Variance explanation")


class CashSessionMovementForm(forms.Form):
    movement_type = forms.ChoiceField(choices=(("EXPENSE", "Cash expense"), ("CASH_IN", "Authorized cash-in"), ("CASH_OUT", "Authorized cash-out")), label="Movement type")
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"), label="Amount (KSh)")
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}), label="Reason")


class CashSessionApprovalForm(forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}), label="Manager review")
