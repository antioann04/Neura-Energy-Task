"""Views for the weekly battery report.

Views should remain thin. They should request prepared context from
WeeklyReportService and render the template, not perform dispatch math.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from energy.services import WeeklyReportService


def weekly_report(request: HttpRequest) -> HttpResponse:
    """Render the required /reports/weekly/ page."""
    report_context = WeeklyReportService().build_context()
    context = {
        "title": "Weekly Battery Dispatch Report",
        "status": (
            "Report ready."
            if report_context.get("has_data")
            else report_context.get("message", "No report data found.")
        ),
        **report_context,
    }
    return render(request, "energy/weekly_report.html", context)
