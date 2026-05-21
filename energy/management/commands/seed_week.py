"""Seed the representative week required by the PDF.

Command responsibilities:
1. Fetch PV from Renewables.ninja.
2. Resample hourly PV to 15-minute intervals.
3. Generate synthetic hotel load.
4. Generate the day/night tariff.
5. Store all input rows in the SQLite database.
6. Run dispatch so the report is immediately viewable.
"""

from django.core.management.base import BaseCommand, CommandError

from energy.services import DispatchService, WeeklyInputBuilder, WeeklyReportService


class Command(BaseCommand):
    """Django command for preparing local demo data."""

    help = "Seed the representative week and compute dispatch output."

    def handle(self, *args: object, **options: object) -> None:
        """Run the data build and dispatch pipeline."""
        try:
            # Keep this command thin: services own the API, data generation,
            # dispatch persistence, and report calculations.
            self.stdout.write("Building representative week input data...")
            interval_count = WeeklyInputBuilder().seed_database()

            self.stdout.write("Running greedy battery dispatch...")
            decisions = DispatchService().run_and_store()

            report = WeeklyReportService().build_context()
        except Exception as exc:
            raise CommandError(f"Failed to seed representative week: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {interval_count} input intervals and "
                f"{len(decisions)} dispatch intervals."
            )
        )
        self.stdout.write(
            f"Period: {report['period_start']:%Y-%m-%d %H:%M} to "
            f"{report['period_end']:%Y-%m-%d %H:%M}"
        )
        self.stdout.write(
            f"Grid spend with battery: EUR {report['grid_spend_with_battery']:.2f}"
        )
        self.stdout.write(
            f"No-battery counterfactual: EUR {report['grid_spend_without_battery']:.2f}"
        )
        self.stdout.write(f"Weekly saving: EUR {report['savings']:.2f}")
        self.stdout.write(f"Battery charged: {report['charged_kwh']:.1f} kWh")
        self.stdout.write(f"Battery discharged: {report['discharged_kwh']:.1f} kWh")
        self.stdout.write(
            f"Solar self-consumption: {report['solar_self_consumption_pct']:.1f}%"
        )
