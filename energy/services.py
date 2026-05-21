"""Application services for data ingestion, dispatch, and reporting.

This module contains orchestration classes that may talk to the database,
Renewables.ninja, pandas, and plotting code. The domain policy itself stays in
energy.domain so it can be tested without Django.
"""

from dataclasses import dataclass
from datetime import date

from energy.domain import BatterySpec, DispatchDecision, GreedyDispatchPolicy


@dataclass(frozen=True)
class SolarRequest:
    """Parameters for a Renewables.ninja PV request."""

    latitude: float = 34.7071
    longitude: float = 33.0226
    capacity_kw: float = 200.0
    start_date: date = date(2019, 7, 1)
    end_date: date = date(2019, 7, 7)
    tilt: float = 30.0
    azimuth: float = 180.0
    system_loss: float = 0.10


class RenewablesNinjaClient:
    """Fetch hourly Limassol PV production from Renewables.ninja."""

    def fetch_hourly_pv(self, request: SolarRequest) -> object:
        """Call the API with token auth and return hourly PV output."""
        raise NotImplementedError("Implement API call and response parsing next.")


class WeeklyInputBuilder:
    """Build and persist the three required 15-minute input series."""

    def build_solar_series(self) -> object:
        """Fetch hourly PV and resample to 15-minute intervals."""
        raise NotImplementedError("Implement solar fetch and resampling next.")

    def build_load_series(self) -> object:
        """Generate a defensible hotel load shape with a 200 kW weekly peak."""
        raise NotImplementedError("Implement synthetic hotel load profile next.")

    def build_tariff_series(self) -> object:
        """Generate the day/night TOU price series from the PDF."""
        raise NotImplementedError("Implement stylised EAC tariff next.")

    def seed_database(self) -> int:
        """Write the representative week into EnergyInterval rows."""
        raise NotImplementedError("Implement database seeding next.")


class DispatchService:
    """Run the dispatch policy and persist DispatchInterval rows."""

    def __init__(self, policy: GreedyDispatchPolicy | None = None) -> None:
        self.policy = policy or GreedyDispatchPolicy(BatterySpec())

    def run_and_store(self) -> list[DispatchDecision]:
        """Read EnergyInterval rows, run policy, and store dispatch decisions."""
        raise NotImplementedError("Implement dispatch persistence next.")


class WeeklyReportService:
    """Compute the numbers required by /reports/weekly/."""

    def build_context(self) -> dict[str, object]:
        """Return spend, savings, kWh totals, self-consumption, and SoC chart data."""
        raise NotImplementedError("Implement weekly report context next.")
