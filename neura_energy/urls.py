"""Top-level URL routing.

The take-home requirement is one report page at /reports/weekly/. The project
router delegates that page to the energy app so the app owns its own URLs.
"""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("energy.urls")),
]
