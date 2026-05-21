"""Views for the weekly battery report.

Views should remain thin. They should request prepared context from
WeeklyReportService and render the template, not perform dispatch math.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def weekly_report(request: HttpRequest) -> HttpResponse:
    """Render the required /reports/weekly/ page."""
    context = {
        "title": "Weekly Battery Dispatch Report",
        "status": "Scaffold ready. Report calculations will be implemented next.",
    }
    return render(request, "energy/weekly_report.html", context)
