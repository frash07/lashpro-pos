from decimal import Decimal
from django import forms
from django.forms import BaseFormSet, formset_factory
from catalog.models import Product, Service
from customers.models import Customer
from accounts.models import User
from payments.models import PaymentTransaction
from .models import Sale


class ProductField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} — KSh {obj.selling_price:,.2f}"


class ServiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} — KSh {obj.price:,.2f}"


class TechnicianField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.get_full_name() or obj.username


class CheckoutDetailsForm(forms.Form):
    idempotency_key = forms.UUIDField(required=False, widget=forms.HiddenInput())
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), required=False,
        empty_label="Walk-in customer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("name")


class CheckoutLineForm(forms.Form):
    product = ProductField(queryset=Product.objects.none(), required=False, empty_label="Choose product")
    service = ServiceField(queryset=Service.objects.none(), required=False, empty_label="Choose service")
    technician = TechnicianField(queryset=User.objects.none(), required=False, empty_label="Choose technician")
    quantity = forms.IntegerField(min_value=1, initial=1)
    discount = forms.DecimalField(required=False, initial=Decimal("0.00"),
        min_value=Decimal("0.00"), max_digits=10, decimal_places=2)
    discount_reason = forms.CharField(required=False, max_length=255,
        label="Discount reason (manager approval)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(active=True).order_by("name")
        self.fields["service"].queryset = Service.objects.filter(active=True).order_by("name")
        self.fields["technician"].queryset = User.objects.filter(
            role=User.Role.TECHNICIAN, is_active=True
        ).order_by("first_name", "username")

    def clean(self):
        data = super().clean()
        if not data:
            return data
        product, service = data.get("product"), data.get("service")
        technician = data.get("technician")
        quantity, discount = data.get("quantity"), data.get("discount") or Decimal("0.00")
        if not product and not service:
            if discount or technician or quantity not in (None, 1):
                raise forms.ValidationError("Choose a product or service for this line.")
            return data
        if bool(product) == bool(service):
            raise forms.ValidationError("Choose exactly one product or service.")
        if service and not technician:
            self.add_error("technician", "Assign a technician to every service.")
        if product and technician:
            self.add_error("technician", "Technicians can only be assigned to service lines.")
        if quantity:
            price = product.selling_price if product else service.price
            if discount > price * quantity:
                self.add_error("discount", "Discount cannot exceed the line subtotal.")
        if discount > Decimal("0.00") and not (data.get("discount_reason") or "").strip():
            self.add_error("discount_reason", "A manager must record a reason for every discount.")
        data["discount_reason"] = (data.get("discount_reason") or "").strip()
        return data


class BaseLineFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(f.cleaned_data and not f.cleaned_data.get("DELETE")
                   and (f.cleaned_data.get("product") or f.cleaned_data.get("service"))
                   for f in self.forms):
            raise forms.ValidationError("Add at least one product or service.")


LineFormSet = formset_factory(CheckoutLineForm, formset=BaseLineFormSet,
    extra=1, can_delete=True, max_num=20, validate_max=True)


class PaymentForm(forms.Form):
    method = forms.ChoiceField(required=False,
        choices=(("", "Choose method"),) + tuple(PaymentTransaction.Method.choices))
    amount = forms.DecimalField(required=False, min_value=Decimal("0.01"),
        max_digits=10, decimal_places=2)
    reference = forms.CharField(required=False, max_length=50)

    def clean(self):
        data = super().clean()
        if not data:
            return data
        method, amount = data.get("method"), data.get("amount")
        reference = (data.get("reference") or "").strip()
        if not method and amount is None and not reference:
            return data
        if not method:
            self.add_error("method", "Choose Cash or M-Pesa.")
        if amount is None:
            self.add_error("amount", "Enter the amount collected.")
        if method == PaymentTransaction.Method.MPESA and not reference:
            self.add_error("reference", "Enter the M-Pesa reference.")
        data["reference"] = reference
        return data


class BalancePaymentForm(forms.Form):
    sale = forms.ModelChoiceField(queryset=Sale.objects.none(), widget=forms.HiddenInput())
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput())
    method = forms.ChoiceField(choices=PaymentTransaction.Method.choices)
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=10, decimal_places=2)
    reference = forms.CharField(required=False, max_length=50)

    def __init__(self, *args, sale_queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sale"].queryset = sale_queryset

    def clean(self):
        data = super().clean()
        if data and data.get("method") == PaymentTransaction.Method.MPESA:
            data["reference"] = (data.get("reference") or "").strip()
            if not data["reference"]:
                self.add_error("reference", "Enter the manual M-Pesa reference.")
        return data


PaymentFormSet = formset_factory(PaymentForm, extra=1, can_delete=True,
    max_num=10, validate_max=True)
