from django.urls import path
from . import views

app_name = "sales"
urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("payments/", views.balance_payments, name="payments"),
    path("services/", views.service_queue, name="services"),
    path("refunds/", views.refunds, name="refunds"),
    path("r/<str:token>/pdf/", views.receipt_pdf, name="receipt_pdf"),
    path("r/<str:token>/", views.receipt, name="receipt"),
]
