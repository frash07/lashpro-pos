from decimal import Decimal

from django import forms
from django.utils import timezone

from payments.models import CashSession
from .models import Expense


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ("expense_date", "category", "description", "supplier", "amount", "payment_status", "payment_method", "reference", "cash_session")
        widgets = {
            "expense_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2, "maxlength": 500}),
            "supplier": forms.TextInput(attrs={"maxlength": 160}),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01", "inputmode": "decimal"}),
            "reference": forms.TextInput(attrs={"maxlength": 80}),
        }
        labels = {
            "expense_date": "Expense date", "category": "Category", "description": "Description",
            "supplier": "Supplier / payee", "amount": "Amount (KSh)", "payment_status": "Payment status",
            "payment_method": "Payment method", "reference": "Payment reference", "cash_session": "Cash drawer session",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expense_date"].initial = self.initial.get("expense_date", timezone.localdate())
        self.fields["amount"].min_value = Decimal("0.01")
        self.fields["cash_session"].queryset = CashSession.objects.filter(
            status=CashSession.Status.OPEN
        ).select_related("cashier").order_by("-opened_at")
        for name in ("cash_session", "payment_method", "reference"):
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        status, method = cleaned.get("payment_status"), cleaned.get("payment_method")
        session, reference = cleaned.get("cash_session"), (cleaned.get("reference") or "").strip()
        if status == Expense.PaymentStatus.PAID and not method:
            self.add_error("payment_method", "Choose how the expense was paid.")
        if status == Expense.PaymentStatus.UNPAID:
            if method:
                self.add_error("payment_method", "Leave payment method blank for an unpaid expense.")
            if reference:
                self.add_error("reference", "Leave payment reference blank until the expense is paid.")
            if session:
                self.add_error("cash_session", "An unpaid expense cannot use a cash drawer.")
        if status == Expense.PaymentStatus.PAID and method == Expense.PaymentMethod.CASH and not session:
            self.add_error("cash_session", "Choose the open cash drawer used to pay this expense.")
        if status == Expense.PaymentStatus.PAID and method != Expense.PaymentMethod.CASH and session:
            self.add_error("cash_session", "Only cash expenses can be linked to a cash drawer.")
        if status == Expense.PaymentStatus.PAID and method == Expense.PaymentMethod.MPESA and not reference:
            self.add_error("reference", "Enter the M-Pesa transaction reference.")
        return cleaned


class ExpenseDateFilterForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError("Start date must be on or before end date.")
        return cleaned
