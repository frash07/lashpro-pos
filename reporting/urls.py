from django.urls import path
from .views import daily_report

app_name = "reporting"
urlpatterns = [path("", daily_report, name="dashboard")]
