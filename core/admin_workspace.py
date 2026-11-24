"""Presentation adapter for selected Django Admin routes.

The original AdminSite/ModelAdmin view always runs first. Its permissions,
querysets, actions, form validation and save hooks are not replaced.
"""
from django.contrib.admin.templatetags.admin_list import date_hierarchy, result_headers
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.contrib.admin.utils import display_for_field, display_for_value, lookup_field
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.urls import reverse
from django.utils.text import capfirst


MODULES = {
    "accounts": ("People & access", "users"),
    "appointments": ("Appointments", "calendar-days"),
    "audit": ("Audit trail", "clipboard-list"),
    "auth": ("Access groups", "key-round"),
    "axes": ("Security & access", "shield-check"),
    "inventory": ("Inventory", "boxes"),
}
REGISTERS = {
    "accounts_user": ("Staff directory", "Review staff accounts, roles and access.", "user-round"),
    "appointments_appointment": ("Appointments", "Review bookings, clients, services and appointment status.", "calendar-days"),
    "appointments_staffavailability": ("Staff availability", "Manage recurring working hours by staff member and weekday.", "calendar-clock"),
    "appointments_stafftimeoff": ("Staff time off", "Manage planned absences and unavailable dates.", "calendar-off"),
    "audit_auditevent": ("Audit events", "Review immutable activity and approval records.", "clipboard-list"),
    "auth_group": ("Access groups", "Manage reusable permission groups for staff accounts.", "key-round"),
    "axes_accesslog": ("Access logs", "Review recorded sign-in and sign-out activity.", "shield-check"),
    "axes_accessattempt": ("Access attempts", "Review authentication attempts and lockout information.", "activity"),
    "axes_accessfailurelog": ("Failed sign-ins", "Review recorded authentication failures.", "shield-alert"),
    "inventory_supplier": ("Suppliers", "Manage supplier contacts and active status.", "truck"),
    "inventory_stockreceipt": ("Stock receipts", "Review recorded stock deliveries and receipt lines.", "package-check"),
    "inventory_stockadjustmentrequest": ("Stock adjustments", "Review stock corrections. Approval changes stock; the requester cannot approve their own request.", "clipboard-check"),
    "inventory_serviceconsumable": ("Service consumables", "Manage the products and quantities consumed by each service.", "package"),
    "inventory_inventorymovement": ("Inventory movements", "Review the inventory ledger and recorded quantity changes.", "arrow-left-right"),
}


def _navigation(context, current_app, current_model, index=False):
    available = {app["app_label"]: app for app in context.get("available_apps", ())}
    groups = [
        {"title": "Workspace", "links": [
            {"label": "Checkout", "url": reverse("sales:checkout"), "icon": "grid-2x2"},
            {"label": "Administration", "url": reverse("admin:index"), "icon": "layout-dashboard", "active": index},
        ]},
        {"title": "Management", "links": []},
        {"title": "Catalogue", "links": []},
    ]
    for key, (label, icon) in MODULES.items():
        if key in available:
            app = available[key]
            url = app["app_url"]
            if key == "auth":
                group = next((item for item in app["models"] if item["object_name"] == "Group"), None)
                if group and group["admin_url"]:
                    url = group["admin_url"]
            groups[1]["links"].append({"label": label, "url": url, "icon": icon, "active": current_app == key})
    for app_key, object_name, label, icon in (
        ("catalog", "Product", "Products", "package"),
        ("catalog", "Service", "Services", "sparkles"),
        ("customers", "Customer", "Clients", "users"),
    ):
        for item in available.get(app_key, {}).get("models", ()):
            if item["object_name"] == object_name and item["admin_url"]:
                groups[2]["links"].append({"label": label, "url": item["admin_url"], "icon": icon})
    return groups


def _field_value(cl, obj, name):
    empty = cl.model_admin.get_empty_value_display()
    try:
        field, attr, value = lookup_field(name, obj, cl.model_admin)
    except ObjectDoesNotExist:
        return {"value": empty}
    boolean = isinstance(field, models.BooleanField) or bool(
        getattr(attr, "boolean", False) or getattr(getattr(attr, "fget", None), "boolean", False)
    )
    if boolean:
        return {"value": "Yes" if value is True else "No" if value is False else empty,
                "tone": "positive" if value is True else "neutral"}
    if field is not None and field.is_relation and getattr(field, "many_to_one", False):
        return {"value": str(value) if value is not None else empty}
    if field is not None:
        return {"value": display_for_field(value, field, empty)}
    return {"value": display_for_value(value, empty)}


def _list_context(request, context, cl):
    columns = [name for name in cl.list_display if name != "action_checkbox"]
    headers = [header for name, header in zip(cl.list_display, result_headers(cl)) if name != "action_checkbox"]
    rows = []
    for obj in cl.result_list:
        cells = []
        for name, header in zip(columns, headers):
            cells.append({"label": capfirst(header["text"]), **_field_value(cl, obj, name)})
        url = ""
        if cl.list_display_links is not None and cl.model_admin.has_view_or_change_permission(request, obj):
            url = add_preserved_filters(
                {"preserved_filters": context.get("preserved_filters", ""), "opts": cl.opts},
                cl.url_for_result(obj),
            )
        rows.append({
            "pk": obj.pk, "title": cells[0]["value"] if cells else str(obj),
            "fields": cells[1:], "url": url,
        })
    pages = []
    if cl.multi_page and not cl.show_all:
        for page in cl.paginator.get_elided_page_range(cl.page_num):
            pages.append({"ellipsis": True} if page == cl.paginator.ELLIPSIS else {
                "number": page, "url": cl.get_query_string({"p": page}), "current": page == cl.page_num,
            })
    sort_options = [("", "Default ordering", not request.GET.get("o"))]
    for index, name in enumerate(cl.list_display):
        if name == "action_checkbox":
            continue
        if not cl.get_ordering_field(name):
            continue
        if cl.sortable_by is not None and name not in cl.sortable_by:
            continue
        label = next((header["text"] for field, header in zip(columns, headers) if field == name), name)
        for value, suffix in ((str(index), "ascending"), ("-" + str(index), "descending")):
            sort_options.append((value, f"{capfirst(label)} · {suffix}", request.GET.get("o") == value))
    current = request.GET.get("o")
    if current and not any(option[2] for option in sort_options):
        sort_options.append((current, "Current ordering", True))
    hierarchy = date_hierarchy(cl) if cl.date_hierarchy else {}
    context.update({
        "workspace_rows": rows,
        "workspace_filters": [{"title": spec.title, "choices": list(spec.choices(cl))} for spec in cl.filter_specs],
        "workspace_search_params": [(key, value) for key, values in request.GET.lists()
                                    if key not in {"q", "o", "p", "all", "e"} for value in values],
        "workspace_sorts": sort_options,
        "workspace_pages": pages,
        "workspace_previous": cl.get_query_string({"p": cl.page_num - 1}) if cl.multi_page and not cl.show_all and cl.page_num > 1 else "",
        "workspace_next": cl.get_query_string({"p": cl.page_num + 1}) if cl.multi_page and not cl.show_all and cl.page_num < cl.paginator.num_pages else "",
        "workspace_show_all": cl.get_query_string({"all": ""}, ["p"]) if cl.can_show_all and cl.multi_page and not cl.show_all else "",
        "workspace_facets": cl.get_query_string(remove=["_facets"]) if cl.add_facets else cl.get_query_string({"_facets": ""}),
        "workspace_hierarchy": hierarchy,
        "workspace_add_url": add_preserved_filters(
            {"preserved_filters": context.get("preserved_filters", ""), "opts": cl.opts},
            reverse(f"admin:{cl.opts.app_label}_{cl.opts.model_name}_add"),
        ) if context.get("has_add_permission") else "",
    })


class StandaloneAdminWorkspaceMiddleware:
    """Switch only the selected successful, non-popup admin template responses."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_template_response(self, request, response):
        match = request.resolver_match
        context = getattr(response, "context_data", None)
        if not match or match.namespace != "admin" or not context or response.status_code != 200:
            return response
        if context.get("is_popup") or "_popup" in request.GET or "_popup" in request.POST:
            return response

        name = match.url_name or ""
        app_label = ""
        register = ""
        template = ""
        if name == "index" and "app_list" in context:
            template = "admin_workspace/index.html"
        elif name == "app_list" and match.kwargs.get("app_label") in MODULES and "app_list" in context:
            app_label = match.kwargs["app_label"]
            template = "admin_workspace/index.html"
        else:
            for suffix in ("_changelist", "_add", "_change"):
                if name.endswith(suffix) and name[:-len(suffix)] in REGISTERS:
                    register = name[:-len(suffix)]
                    app_label = register.split("_", 1)[0]
                    if suffix == "_changelist" and "cl" in context:
                        cl = context["cl"]
                        # Editable lists need the native formset; none of the selected registers use them.
                        if cl.list_editable or cl.is_popup:
                            return response
                        _list_context(request, context, cl)
                        template = "admin_workspace/change_list.html"
                    elif suffix != "_changelist" and "adminform" in context:
                        template = "admin_workspace/change_form.html"
                    break
        if not template:
            return response

        module, module_icon = MODULES.get(app_label, ("Administration", "layout-dashboard"))
        title, description, icon = REGISTERS.get(register, (module, "Choose a register to manage studio operations.", module_icon))
        context.update({
            "workspace_module": module,
            "workspace_title": title,
            "workspace_description": description,
            "workspace_icon": icon,
            "workspace_app": app_label,
            "workspace_register": register,
            "workspace_is_index": name == "index",
            "workspace_nav": _navigation(context, app_label, register, index=name == "index"),
            "workspace_app_url": reverse("admin:app_list", kwargs={"app_label": app_label}) if app_label else "",
            "workspace_list_url": reverse(f"admin:{register}_changelist") if register else "",
        })
        if template.endswith("change_form.html"):
            opts = context["opts"]
            context["workspace_list_url"] = add_preserved_filters(
                {"preserved_filters": context.get("preserved_filters", ""), "opts": opts},
                context["workspace_list_url"],
            )
            context["workspace_can_save"] = (
                context.get("has_change_permission") or context.get("add") and context.get("has_add_permission")
            ) and context.get("show_save", True)
            context["workspace_can_save_continue"] = context["workspace_can_save"] and context.get("has_view_permission", True) and context.get("show_save_and_continue", True)
            context["workspace_can_save_add"] = context["workspace_can_save"] and context.get("has_add_permission") and not context.get("save_as")
            if context.get("original"):
                from django.contrib.admin.utils import quote
                object_id = quote(context["original"].pk)
                context["workspace_history_url"] = reverse(f"admin:{register}_history", args=[object_id])
                if context.get("has_delete_permission"):
                    context["workspace_delete_url"] = add_preserved_filters(
                        {"preserved_filters": context.get("preserved_filters", ""), "opts": opts},
                        reverse(f"admin:{register}_delete", args=[object_id]),
                    )
        response.template_name = template
        return response
