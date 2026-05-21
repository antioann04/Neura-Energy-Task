"""Seed the representative week required by the PDF.

Planned command responsibilities:
1. Fetch PV from Renewables.ninja.
2. Resample hourly PV to 15-minute intervals.
3. Generate synthetic hotel load.
4. Generate the day/night tariff.
5. Store all input rows in the SQLite database.
6. Run dispatch so the report is immediately viewable.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Django command for preparing local demo data."""

    help = "Seed the representative week and compute dispatch output."

    def handle(self, *args: object, **options: object) -> None:
        """Run the data build and dispatch pipeline."""
        self.stdout.write(
            self.style.WARNING("Scaffold only: seed_week implementation comes next.")
        )
