from decimal import Decimal
from django import forms
from catalog.models import Product


class StockReceiptForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(active=True).order_by("name"))
    quantity = forms.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"))
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
