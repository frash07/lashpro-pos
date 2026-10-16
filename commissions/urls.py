from django.urls import path
from .views import commission_dashboard

app_name = "commissions"
urlpatterns = [path("", commission_dashboard, name="dashboard")]
