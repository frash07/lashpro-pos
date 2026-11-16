from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.book, name="book"),
    path("availability/", views.availability, name="availability"),
    path("confirmation/<str:token>/", views.detail, name="detail"),
    path("account/", views.account_appointments, name="account"),
    path("account/<int:pk>/cancel/", views.cancel_appointment, name="cancel"),
    path("manage/", views.staff_day, name="staff-day"),
    path("manage/<int:pk>/status/", views.update_status, name="update-status"),
]
