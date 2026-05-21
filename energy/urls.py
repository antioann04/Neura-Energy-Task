"""URL routes owned by the energy app."""

from django.urls import path

from energy import views


app_name = "energy"

urlpatterns = [
    path("reports/weekly/", views.weekly_report, name="weekly-report"),
]
