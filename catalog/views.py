import time
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from accounts.models import User
from .forms import ProductImportUploadForm
from .product_imports import create_products_from_import, preview_product_import

SESSION_KEY = "catalog_product_import_preview"
PREVIEW_TTL_SECONDS = 30 * 60


def _manager_only(user):
    return bool(
        getattr(user, "is_active", False)
        and (user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER})
    )


def _render_import(request, upload_form=None, preview=None):
    preview = preview or request.session.get(SESSION_KEY)
    if preview and time.time() - preview.get("created_at", 0) > PREVIEW_TTL_SECONDS:
        request.session.pop(SESSION_KEY, None)
        preview = None
        messages.info(request, "The product preview expired. Upload the file again.")
    if preview:
        preview["row_count"] = len(preview.get("rows", []))
        preview["has_errors"] = any(row.get("errors") for row in preview.get("rows", []))
        preview["can_confirm"] = preview["row_count"] > 0 and not preview["has_errors"]
    return render(request, "inventory/product_import.html", {
        "upload_form": upload_form or ProductImportUploadForm(),
        "preview": preview,
    })


@login_required(login_url="login")
@never_cache
def product_import_view(request):
    if not _manager_only(request.user):
        raise PermissionDenied

    if request.method != "POST":
        return _render_import(request)

    stage = request.POST.get("stage")
    if stage == "preview":
        request.session.pop(SESSION_KEY, None)
        upload_form = ProductImportUploadForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            return _render_import(request, upload_form=upload_form)
        try:
            rows = preview_product_import(upload_form.cleaned_data["file"])
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
            return _render_import(request, upload_form=ProductImportUploadForm())
        uploaded_name = upload_form.cleaned_data["file"].name.replace("\\", "/").rsplit("/", 1)[-1][:120]
        preview = {
            "batch_id": uuid.uuid4().hex,
            "user_id": request.user.pk,
            "created_at": time.time(),
            "filename": uploaded_name or "products upload",
            "rows": rows,
        }
        request.session[SESSION_KEY] = preview
        return _render_import(request, preview=preview)

    if stage == "cancel":
        request.session.pop(SESSION_KEY, None)
        messages.info(request, "The product import preview was discarded.")
        return redirect("inventory:product_import")

    if stage == "confirm":
        preview = request.session.get(SESSION_KEY)
        if (
            not preview
            or preview.get("user_id") != request.user.pk
            or request.POST.get("batch_id") != preview.get("batch_id")
            or time.time() - preview.get("created_at", 0) > PREVIEW_TTL_SECONDS
        ):
            request.session.pop(SESSION_KEY, None)
            messages.error(request, "The preview is missing or expired. Upload and preview the file again.")
            return redirect("inventory:product_import")
        if any(row.get("errors") for row in preview.get("rows", [])):
            messages.error(request, "Fix every row error and preview the corrected file before importing.")
            return redirect("inventory:product_import")
        try:
            products = create_products_from_import(
                rows=preview["rows"], actor=request.user,
                batch_id=preview["batch_id"], source_filename=preview["filename"],
            )
        except ValidationError as exc:
            request.session.pop(SESSION_KEY, None)
            for error in exc.messages:
                messages.error(request, error)
            return redirect("inventory:product_import")
        request.session.pop(SESSION_KEY, None)
        messages.success(request, f"Imported {len(products)} products. Opening stock was recorded in the inventory ledger.")
        return redirect("inventory:product_import")

    messages.error(request, "Choose preview, confirm, or cancel for the product import.")
    return redirect("inventory:product_import")
