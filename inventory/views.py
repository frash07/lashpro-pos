from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from accounts.models import User
from .forms import StockReceiptForm
from .services import receive_stock


@login_required(login_url="login")
def receive_stock_view(request):
    if not (request.user.is_superuser or getattr(request.user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}):
        raise PermissionDenied
    form = StockReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            movement = receive_stock(
                product=form.cleaned_data["product"], quantity=form.cleaned_data["quantity"],
                unit_cost=form.cleaned_data["unit_cost"], reason=form.cleaned_data["reason"], actor=request.user,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"Received {movement.quantity_delta} units of {movement.product}.")
            return redirect("inventory:receive")
    return render(request, "inventory/receive.html", {"form": form})
