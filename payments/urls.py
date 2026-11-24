from django.urls import path
from .views import (
    cash_session_dashboard, reconciliation_queue,
    c2b_confirmation, c2b_inbox, c2b_validation, register_c2b_callbacks,
    mpesa_stk_callback, mpesa_stk_initiate,
)

app_name = "payments"
urlpatterns = [
    path("mpesa/stk/initiate/", mpesa_stk_initiate, name="mpesa-stk-initiate"),
    path("mpesa/stk/callback/<str:token>/", mpesa_stk_callback, name="mpesa-stk-callback"),
    path("c2b/confirmation/<str:token>/", c2b_confirmation, name="c2b-confirmation"),
    path("c2b/validation/<str:token>/", c2b_validation, name="c2b-validation"),
    path("c2b/register/", register_c2b_callbacks, name="c2b-register"),
    path("c2b/inbox/", c2b_inbox, name="c2b-inbox"),
    path("reconciliation/", reconciliation_queue, name="reconciliation"),
    path("cash-session/", cash_session_dashboard, name="cash-session"),
]
