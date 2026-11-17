from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.models import User
from .forms import ExpenseDateFilterForm, ExpenseForm
from .models import Expense
from .services import record_expense


def _can_manage_expenses(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


@login_required(login_url="login")
def dashboard(request):
    if not _can_manage_expenses(request.user):
        raise PermissionDenied

    form = ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            expense = record_expense(actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            if hasattr(exc, "error_dict"):
                for field, errors in exc.error_dict.items():
                    for error in errors:
                        form.add_error(field if field in form.fields else None, error)
            else:
                form.add_error(None, exc.messages[0])
        else:
            messages.success(request, f"Expense #{expense.pk} recorded.")
            return redirect("expenses:dashboard")

    today = timezone.localdate()
    default_start, default_end = today.replace(day=1), today
    if request.GET:
        filters = ExpenseDateFilterForm(request.GET)
        if filters.is_valid():
            start = filters.cleaned_data.get("start_date") or default_start
            end = filters.cleaned_data.get("end_date") or default_end
        else:
            start, end = default_start, default_end
            filters = ExpenseDateFilterForm(initial={"start_date": start, "end_date": end})
    else:
        start, end = default_start, default_end
        filters = ExpenseDateFilterForm(initial={"start_date": start, "end_date": end})

    expenses = Expense.objects.select_related("created_by", "cash_session__cashier", "cash_movement")
    expenses = expenses.filter(expense_date__range=(start, end))
    total = expenses.aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    paid_total = expenses.filter(payment_status=Expense.PaymentStatus.PAID).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    unpaid_total = expenses.filter(payment_status=Expense.PaymentStatus.UNPAID).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    category_totals = expenses.values("category").annotate(value=Sum("amount"), count=Count("pk")).order_by("-value")
    category_labels = dict(Expense.Category.choices)
    category_summary = [
        {"label": category_labels.get(row["category"], row["category"]), "amount": row["value"], "count": row["count"]}
        for row in category_totals
    ]
    return render(request, "expenses/dashboard.html", {
        "form": form, "filters": filters, "expenses": expenses[:200],
        "total": total, "paid_total": paid_total, "unpaid_total": unpaid_total,
        "category_summary": category_summary, "start": start, "end": end,
    })
