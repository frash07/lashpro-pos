from django.urls import path
from catalog.views import product_import_view
from .views import receive_stock_view

app_name = "inventory"
urlpatterns = [
    path("receive/", receive_stock_view, name="receive"),
    path("products/import/", product_import_view, name="product_import"),
]
