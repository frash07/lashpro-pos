from django.urls import path

from . import views

app_name = "storefront"

urlpatterns = [
    path("", views.home, name="home"),
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart-add"),
    path("cart/update/<int:product_id>/", views.cart_update, name="cart-update"),
    path("cart/remove/<int:product_id>/", views.cart_remove, name="cart-remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("order/<str:token>/", views.order_detail, name="order-detail"),
    path("account/register/", views.register, name="register"),
    path("account/login/", views.customer_login, name="login"),
    path("account/logout/", views.customer_logout, name="logout"),
    path("account/orders/", views.account_orders, name="account-orders"),
]
