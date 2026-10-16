from django.urls import path
from .views import cash_session_dashboard, reconciliation_queue

app_name = "payments"
urlpatterns = [
    path("reconciliation/", reconciliation_queue, name="reconciliation"),
    path("cash-session/", cash_session_dashboard, name="cash-session"),
]
