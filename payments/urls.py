from django.urls import path
from .views import (
    cash_session_dashboard, reconciliation_queue,
    mpesa_stk_callback, mpesa_stk_initiate,
)

app_name = "payments"
urlpatterns = [
    path("mpesa/stk/initiate/", mpesa_stk_initiate, name="mpesa-stk-initiate"),
    path("mpesa/stk/callback/<str:token>/", mpesa_stk_callback, name="mpesa-stk-callback"),
    path("reconciliation/", reconciliation_queue, name="reconciliation"),
    path("cash-session/", cash_session_dashboard, name="cash-session"),
]
