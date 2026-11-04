import uuid
from decimal import Decimal

from django import forms
from django.forms import formset_factory
from django.utils import timezone

from catalog.models import Product
from .models import StockReceipt, Supplier


class StockReceiptForm(forms.Form):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(active=True).order_by("name"),
        empty_label="Choose a supplier",
    )
    reference_type = forms.ChoiceField(choices=StockReceipt.ReferenceType.choices)
    supplier_reference = forms.CharField(
        max_length=100,
        label="Supplier invoice / document number",
        help_text="This reference is unique for this supplier and document type.",
    )
    delivery_note_number = forms.CharField(max_length=100, required=False, label="Delivery note number")
    received_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    notes = forms.CharField(
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)


class StockReceiptLineForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(active=True).order_by("name"),
        empty_label="Choose a product",
    )
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        widget=forms.NumberInput(attrs={"min": "0.001", "step": "0.001"}),
    )
    unit_cost = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
        label="Unit cost (KSh)",
    )


class BaseStockReceiptLineFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            product = form.cleaned_data.get("product")
            if product is None:
                continue
            if product.pk in seen:
                raise forms.ValidationError(
                    "Each product may appear once on a receipt. Combine duplicate product quantities."
                )
            seen.add(product.pk)


StockReceiptLineFormSet = formset_factory(
    StockReceiptLineForm,
    formset=BaseStockReceiptLineFormSet,
    extra=1,
    min_num=1,
    validate_min=True,
    max_num=50,
    validate_max=True,
    can_delete=True,
)
