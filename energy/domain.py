"""Pure Python domain objects for battery dispatch.

This module should stay independent from Django. That makes the dispatch logic
easy to test and proves to reviewers that the policy does not live in a view.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BatterySpec:
    """Physical battery limits used by the greedy dispatch policy."""

    capacity_kwh: float = 400.0
    max_power_kw: float = 200.0
    min_soc_fraction: float = 0.10
    max_soc_fraction: float = 0.95
    round_trip_efficiency: float = 0.88


@dataclass(frozen=True)
class IntervalInput:
    """One 15-minute timestep of solar, load, and tariff input data."""

    timestamp: datetime
    solar_kw: float
    load_kw: float
    grid_price_eur_per_kwh: float


@dataclass(frozen=True)
class DispatchDecision:
    """One timestep of dispatch output and energy accounting."""

    timestamp: datetime
    action: str
    soc_kwh: float
    battery_power_kw: float
    solar_to_load_kwh: float
    solar_to_battery_kwh: float
    battery_to_load_kwh: float
    grid_to_load_kwh: float
    curtailed_solar_kwh: float


class GreedyDispatchPolicy:
    """Dispatch battery using the simple policy allowed by the PDF.

    Planned behavior:
    - Solar serves load first.
    - Surplus solar charges the battery within SoC and power limits.
    - During day-rate hours, the battery discharges to reduce grid import.
    - No grid export is allowed; unusable surplus solar is curtailed.
    - SoC remains between 10% and 95%.
    """

    def __init__(self, battery: BatterySpec, interval_hours: float = 0.25) -> None:
        self.battery = battery
        self.interval_hours = interval_hours

    def run_week(self, intervals: list[IntervalInput]) -> list[DispatchDecision]:
        """Return dispatch decisions for a full representative week."""
        raise NotImplementedError("Implement greedy weekly dispatch next.")
