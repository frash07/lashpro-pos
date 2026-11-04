from django.urls import path

from catalog.views import product_import_view
from .views import receive_stock_view, stock_receipt_detail_view, stock_receipts_view

app_name = "inventory"
urlpatterns = [
    path("receive/", receive_stock_view, name="receive"),
    path("receipts/", stock_receipts_view, name="receipts"),
    path("receipts/<int:receipt_id>/", stock_receipt_detail_view, name="receipt_detail"),
    path("products/import/", product_import_view, name="product_import"),
]
