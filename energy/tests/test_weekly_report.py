"""Tests for weekly report calculations and missing-data behavior."""

from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from django.test import TestCase

from energy.models import DispatchInterval, EnergyInterval
from energy.services import WeeklyReportService


START = datetime(2019, 7, 1, 9, 0, tzinfo=ZoneInfo("Asia/Nicosia"))


def model_manager(model: type[Any]) -> Any:
    """Return Django's dynamic model manager in a Pylance-friendly way."""
    return cast(Any, model).objects


class WeeklyReportServiceTests(TestCase):
    """Database-backed coverage for report math used by /reports/weekly/."""

    def assert_close(self, actual: float, expected: float, places: int = 7) -> None:
        """Keep report-money and energy assertions readable."""
        self.assertAlmostEqual(actual, expected, places=places)

    def create_interval(
        self,
        index: int,
        *,
        solar_kw: float,
        load_kw: float,
        price: float,
    ) -> EnergyInterval:
        """Create one 15-minute input row in the test database."""
        return cast(
            EnergyInterval,
            model_manager(EnergyInterval).create(
                timestamp=START + timedelta(minutes=15 * index),
                solar_kw=solar_kw,
                load_kw=load_kw,
                grid_price_eur_per_kwh=price,
            ),
        )

    def create_dispatch(
        self,
        interval: EnergyInterval,
        *,
        action: str,
        soc_kwh: float,
        battery_power_kw: float = 0.0,
        solar_to_load_kwh: float = 0.0,
        solar_to_battery_kwh: float = 0.0,
        battery_to_load_kwh: float = 0.0,
        grid_to_load_kwh: float = 0.0,
        curtailed_solar_kwh: float = 0.0,
    ) -> DispatchInterval:
        """Create one dispatch row with explicit energy accounting."""
        return cast(
            DispatchInterval,
            model_manager(DispatchInterval).create(
                interval=interval,
                action=action,
                soc_kwh=soc_kwh,
                battery_power_kw=battery_power_kw,
                solar_to_load_kwh=solar_to_load_kwh,
                solar_to_battery_kwh=solar_to_battery_kwh,
                battery_to_load_kwh=battery_to_load_kwh,
                grid_to_load_kwh=grid_to_load_kwh,
                curtailed_solar_kwh=curtailed_solar_kwh,
            ),
        )

    def test_empty_database_returns_actionable_message(self) -> None:
        """Tell the user to seed data when no intervals exist."""
        context = WeeklyReportService().build_context()

        self.assertFalse(context["has_data"])
        self.assertIn("seed_week", context["message"])

    def test_report_calculates_spend_savings_energy_and_self_consumption(self) -> None:
        """Aggregate the exact metrics required by the PDF."""
        first = self.create_interval(0, solar_kw=40.0, load_kw=100.0, price=0.30)
        second = self.create_interval(1, solar_kw=200.0, load_kw=0.0, price=0.30)
        self.create_dispatch(
            first,
            action="discharge",
            soc_kwh=94.7,
            battery_power_kw=20.0,
            solar_to_load_kwh=10.0,
            battery_to_load_kwh=5.0,
            grid_to_load_kwh=10.0,
        )
        self.create_dispatch(
            second,
            action="charge",
            soc_kwh=122.8,
            battery_power_kw=-120.0,
            solar_to_battery_kwh=30.0,
            curtailed_solar_kwh=20.0,
        )

        context = WeeklyReportService().build_context()

        self.assertTrue(context["has_data"])
        self.assertEqual(context["interval_count"], 2)
        self.assert_close(context["grid_spend_without_battery"], 4.50)
        self.assert_close(context["grid_spend_with_battery"], 3.00)
        self.assert_close(context["savings"], 1.50)
        self.assert_close(context["charged_kwh"], 30.0)
        self.assert_close(context["discharged_kwh"], 5.0)
        self.assert_close(context["total_pv_kwh"], 60.0)
        self.assert_close(context["curtailed_solar_kwh"], 20.0)
        self.assert_close(context["solar_self_consumption_pct"], 66.6666667)
        self.assertEqual(len(context["dispatch_rows"]), 2)
        self.assertEqual(len(context["soc_points"]), 2)
        self.assertTrue(context["soc_chart_svg"].lstrip().startswith("<?xml"))

    def test_zero_pv_week_has_zero_self_consumption(self) -> None:
        """Avoid divide-by-zero when the representative period has no PV."""
        interval = self.create_interval(0, solar_kw=0.0, load_kw=100.0, price=0.15)
        self.create_dispatch(
            interval,
            action="idle",
            soc_kwh=40.0,
            grid_to_load_kwh=25.0,
        )

        context = WeeklyReportService().build_context()

        self.assert_close(context["total_pv_kwh"], 0.0)
        self.assert_close(context["solar_self_consumption_pct"], 0.0)
        self.assert_close(context["grid_spend_without_battery"], 3.75)
        self.assert_close(context["grid_spend_with_battery"], 3.75)
        self.assert_close(context["savings"], 0.0)

    def test_missing_dispatch_data_raises_clear_error(self) -> None:
        """Fail loudly when inputs exist but dispatch has not been computed."""
        self.create_interval(0, solar_kw=0.0, load_kw=100.0, price=0.15)

        with self.assertRaisesRegex(RuntimeError, "Dispatch data missing"):
            WeeklyReportService().build_context()
