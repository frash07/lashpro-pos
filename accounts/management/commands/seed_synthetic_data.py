import os
import uuid
from decimal import Decimal
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from accounts.models import User
from catalog.models import Product, Service
from customers.models import Customer
from inventory.models import InventoryMovement, ServiceConsumable
from inventory.services import receive_stock
from payments.models import CashSession
from payments.services import open_cash_session
from sales.models import Sale
from sales.services import checkout_sale
from commissions.services import complete_service_line


SEED_VERSION = "lashpro-synthetic-alpha-v1"
SYNTHETIC_SALE_KEY = uuid.UUID("d0086c12-14dd-4aa8-b0c0-1112a1100001")
OPENING_STOCK_REASON = f"Synthetic test opening stock ({SEED_VERSION})"
SYNTHETIC_USERS = (
    ("demo_manager", "demo_manager@synthetic.invalid", User.Role.MANAGER, "Demo", "Manager"),
    ("demo_cashier", "demo_cashier@synthetic.invalid", User.Role.CASHIER, "Demo", "Cashier"),
    ("demo_technician_1", "demo_technician_1@synthetic.invalid", User.Role.TECHNICIAN, "Demo", "Technician One"),
    ("demo_technician_2", "demo_technician_2@synthetic.invalid", User.Role.TECHNICIAN, "Demo", "Technician Two"),
)
SYNTHETIC_PRODUCTS = (
    {
        "sku": "SYN-LASH-GLUE-001",
        "name": "[Synthetic Test] Lash Adhesive",
        "cost_price": Decimal("180.00"),
        "selling_price": Decimal("350.00"),
        "reorder_level": Decimal("5.000"),
        "opening_stock": Decimal("30.000"),
    },
    {
        "sku": "SYN-LASH-SHAMPOO-001",
        "name": "[Synthetic Test] Lash Cleanser",
        "cost_price": Decimal("250.00"),
        "selling_price": Decimal("450.00"),
        "reorder_level": Decimal("4.000"),
        "opening_stock": Decimal("20.000"),
    },
    {
        "sku": "SYN-UNDER-EYE-PADS-001",
        "name": "[Synthetic Test] Under-Eye Pads",
        "cost_price": Decimal("12.00"),
        "selling_price": Decimal("25.00"),
        "reorder_level": Decimal("20.000"),
        "opening_stock": Decimal("100.000"),
    },
)
SYNTHETIC_SERVICES = (
    {
        "name": "[Synthetic Test] Classic Lash Set",
        "duration_minutes": 90,
        "price": Decimal("2500.00"),
        "commission_eligible": True,
        "commission_rate": Decimal("0.4000"),
    },
    {
        "name": "[Synthetic Test] Hybrid Lash Set",
        "duration_minutes": 105,
        "price": Decimal("3200.00"),
        "commission_eligible": True,
        "commission_rate": Decimal("0.4000"),
    },
    {
        "name": "[Synthetic Test] Lash Lift",
        "duration_minutes": 60,
        "price": Decimal("1800.00"),
        "commission_eligible": True,
        "commission_rate": Decimal("0.3500"),
    },
)


class Command(BaseCommand):
    help = (
        "Create fictional LashPro test users, customers, catalog items and ledgered "
        "opening stock. Refuses to run without explicit test-environment safeguards."
    )

    def handle(self, *args, **options):
        if os.environ.get("SYNTHETIC_DATA_ENABLED", "").strip().lower() != "true":
            raise CommandError("Seeding is disabled. Set SYNTHETIC_DATA_ENABLED=true only for a disposable test environment.")
        if os.environ.get("DJANGO_ENV", "").strip().lower() != "synthetic-test":
            raise CommandError("Set DJANGO_ENV=synthetic-test on the dedicated test service before seeding.")
        if connection.vendor != "postgresql":
            raise CommandError("Synthetic Alpha seeding is supported only on PostgreSQL.")
        database_name = str(connection.settings_dict.get("NAME", ""))
        confirmation = os.environ.get("SYNTHETIC_DATA_CONFIRM_DATABASE", "")
        if not database_name or confirmation != database_name:
            raise CommandError(
                "SYNTHETIC_DATA_CONFIRM_DATABASE must exactly match the target PostgreSQL database name "
                f"({database_name or 'unknown'}). This is a deliberate target-database confirmation."
            )

        password = os.environ.get("SYNTHETIC_STAFF_PASSWORD", "")
        if not password:
            raise CommandError("Set SYNTHETIC_STAFF_PASSWORD to a strong, test-only password for newly created demo staff.")

        created = {"users": 0, "customers": 0, "products": 0, "services": 0, "stock_receipts": 0, "sales": 0, "completed_services": 0}
        with transaction.atomic():
            users = {}
            for username, email, role, first_name, last_name in SYNTHETIC_USERS:
                user = User.objects.filter(username=username).first()
                if user is None:
                    candidate = User(
                        username=username,
                        email=email,
                        role=role,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    try:
                        validate_password(password, user=candidate)
                    except ValidationError as exc:
                        raise CommandError(
                            "SYNTHETIC_STAFF_PASSWORD does not meet Django's password policy."
                        ) from exc
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        role=role,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    created["users"] += 1
                else:
                    # Never rewrite passwords, roles, names, or privileges on reruns.
                    if (
                        user.email != email
                        or user.role != role
                        or user.is_superuser
                        or user.is_staff
                        or not user.is_active
                    ):
                        raise CommandError(
                            f"Existing account {username!r} differs from its reserved synthetic identity. "
                            "No account was changed; inspect it manually."
                        )
                users[role, username] = user

            manager = users[User.Role.MANAGER, "demo_manager"]

            for spec in SYNTHETIC_PRODUCTS:
                product, was_created = Product.objects.get_or_create(
                    sku=spec["sku"],
                    defaults={
                        "name": spec["name"],
                        "cost_price": spec["cost_price"],
                        "selling_price": spec["selling_price"],
                        "reorder_level": spec["reorder_level"],
                        "on_hand": Decimal("0.000"),
                        "active": True,
                    },
                )
                if was_created:
                    created["products"] += 1
                elif not product.name.startswith("[Synthetic Test] "):
                    raise CommandError(
                        f"SKU {spec['sku']!r} is reserved for synthetic data but belongs to a non-synthetic product."
                    )

                receipt_exists = InventoryMovement.objects.filter(
                    product=product,
                    movement_type=InventoryMovement.Type.PURCHASE,
                    reason=OPENING_STOCK_REASON,
                ).exists()
                if not receipt_exists:
                    receive_stock(
                        product=product,
                        quantity=spec["opening_stock"],
                        unit_cost=spec["cost_price"],
                        reason=OPENING_STOCK_REASON,
                        actor=manager,
                    )
                    created["stock_receipts"] += 1

            products_by_sku = {p.sku: p for p in Product.objects.filter(sku__startswith="SYN-")}
            glue = products_by_sku["SYN-LASH-GLUE-001"]

            services = {}
            for spec in SYNTHETIC_SERVICES:
                service, was_created = Service.objects.get_or_create(
                    name=spec["name"],
                    defaults={
                        "duration_minutes": spec["duration_minutes"],
                        "price": spec["price"],
                        "commission_eligible": spec["commission_eligible"],
                        "commission_rate": spec["commission_rate"],
                        "active": True,
                    },
                )
                if was_created:
                    created["services"] += 1
                services[service.name] = service

            # A recorded requirement lets service completion exercise the stock ledger.
            ServiceConsumable.objects.get_or_create(
                service=services["[Synthetic Test] Classic Lash Set"],
                product=glue,
                defaults={"quantity_per_service": Decimal("0.025"), "active": True},
            )

            customers = {}
            for number in range(1, 6):
                name = f"Synthetic Test Customer {number:03d}"
                customer, was_created = Customer.objects.get_or_create(
                    name=name,
                    defaults={
                        "phone": "",
                        "notes": f"Fictional QA record ({SEED_VERSION}); no real customer data.",
                    },
                )
                customers[number] = customer
                if was_created:
                    created["customers"] += 1

            # Add one stable, synthetic mixed sale so reports, stock, commissions,
            # cash sessions and manual-M-Pesa reconciliation are usable immediately.
            cashier = users[User.Role.CASHIER, "demo_cashier"]
            technician = users[User.Role.TECHNICIAN, "demo_technician_1"]
            sample_sale = Sale.objects.filter(checkout_idempotency_key=SYNTHETIC_SALE_KEY).first()
            if sample_sale is None:
                active_session = CashSession.objects.filter(
                    cashier=cashier,
                    status__in=(CashSession.Status.OPEN, CashSession.Status.PENDING_APPROVAL),
                ).first()
                if active_session and active_session.status != CashSession.Status.OPEN:
                    raise CommandError(
                        "The synthetic cashier has a session awaiting approval; review it before seeding the sample sale."
                    )
                if active_session is None:
                    open_cash_session(
                        cashier=cashier,
                        opening_float=Decimal("2000.00"),
                        actor=manager,
                    )
                sample_sale = checkout_sale(
                    cashier=cashier,
                    customer=customers[1],
                    items=[
                        {"product_id": products_by_sku["SYN-LASH-SHAMPOO-001"].pk, "quantity": 1},
                        {
                            "service_id": services["[Synthetic Test] Classic Lash Set"].pk,
                            "technician_id": technician.pk,
                        },
                    ],
                    payments=[
                        {"method": "CASH", "amount": "1000.00"},
                        {"method": "MPESA", "amount": "1950.00", "reference": "SYNTHMPESA001"},
                    ],
                    idempotency_key=SYNTHETIC_SALE_KEY,
                )
                created["sales"] += 1

            service_line = sample_sale.lines.filter(
                service=services["[Synthetic Test] Classic Lash Set"]
            ).first()
            if service_line and not service_line.service_completed_at:
                complete_service_line(
                    sale_line=service_line,
                    technician=technician,
                    actor=manager,
                )
                created["completed_services"] += 1

        self.stdout.write(self.style.SUCCESS(
            "Synthetic test seed complete. "
            + ", ".join(f"{key} created: {value}" for key, value in created.items())
        ))
        self.stdout.write(
            "Demo usernames: demo_manager, demo_cashier, demo_technician_1, demo_technician_2. "
            "The supplied password is only applied when each account is first created."
        )
