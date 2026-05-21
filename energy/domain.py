"""Pure Python domain objects for battery dispatch.

This module should stay independent from Django. That makes the dispatch logic
easy to test and proves to reviewers that the policy does not live in a view.
"""

from dataclasses import dataclass
from datetime import datetime
from math import sqrt


EPSILON = 1e-9


@dataclass(frozen=True)
class BatterySpec:
    """Physical battery limits used by the greedy dispatch policy."""

    capacity_kwh: float = 400.0
    max_power_kw: float = 200.0
    min_soc_fraction: float = 0.10
    max_soc_fraction: float = 0.95
    round_trip_efficiency: float = 0.88

    def __post_init__(self) -> None:
        """Reject physically impossible battery settings early."""
        if self.capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be positive.")
        if self.max_power_kw <= 0:
            raise ValueError("max_power_kw must be positive.")
        if not 0 <= self.min_soc_fraction < self.max_soc_fraction <= 1:
            raise ValueError("SoC fractions must satisfy 0 <= min < max <= 1.")
        if not 0 < self.round_trip_efficiency <= 1:
            raise ValueError("round_trip_efficiency must be in the range (0, 1].")

    @property
    def min_soc_kwh(self) -> float:
        """Minimum allowed stored energy."""
        return self.capacity_kwh * self.min_soc_fraction

    @property
    def max_soc_kwh(self) -> float:
        """Maximum allowed stored energy."""
        return self.capacity_kwh * self.max_soc_fraction

    @property
    def charge_efficiency(self) -> float:
        """One-way charge efficiency using a symmetric round-trip split."""
        return sqrt(self.round_trip_efficiency)

    @property
    def discharge_efficiency(self) -> float:
        """One-way discharge efficiency using a symmetric round-trip split."""
        return sqrt(self.round_trip_efficiency)


@dataclass(frozen=True)
class IntervalInput:
    """One 15-minute timestep of solar, load, and tariff input data."""

    timestamp: datetime
    solar_kw: float
    load_kw: float
    grid_price_eur_per_kwh: float

    def __post_init__(self) -> None:
        """Reject negative physical or tariff inputs."""
        if self.solar_kw < 0:
            raise ValueError("solar_kw cannot be negative.")
        if self.load_kw < 0:
            raise ValueError("load_kw cannot be negative.")
        if self.grid_price_eur_per_kwh < 0:
            raise ValueError("grid_price_eur_per_kwh cannot be negative.")


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

    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"

    def __init__(
        self,
        battery: BatterySpec,
        interval_hours: float = 0.25,
        initial_soc_fraction: float | None = None,
    ) -> None:
        """Create the policy.

        The default starting SoC is the minimum allowed SoC. This is conservative
        for a one-week counterfactual because it avoids crediting the battery with
        free energy before the modeled week starts.
        """
        if interval_hours <= 0:
            raise ValueError("interval_hours must be positive.")
        if initial_soc_fraction is not None and not (
            battery.min_soc_fraction
            <= initial_soc_fraction
            <= battery.max_soc_fraction
        ):
            raise ValueError("initial_soc_fraction must be inside the SoC bounds.")

        self.battery = battery
        self.interval_hours = interval_hours
        self.initial_soc_fraction = (
            battery.min_soc_fraction
            if initial_soc_fraction is None
            else initial_soc_fraction
        )

    def run_week(self, intervals: list[IntervalInput]) -> list[DispatchDecision]:
        """Return dispatch decisions for a full representative week."""
        if not intervals:
            return []

        cheap_price = min(interval.grid_price_eur_per_kwh for interval in intervals)
        soc_kwh = self.battery.capacity_kwh * self.initial_soc_fraction
        decisions: list[DispatchDecision] = []
        previous_timestamp: datetime | None = None

        for interval in intervals:
            if previous_timestamp is not None and interval.timestamp <= previous_timestamp:
                raise ValueError("intervals must be in strictly increasing timestamp order.")
            previous_timestamp = interval.timestamp

            decision, soc_kwh = self._dispatch_interval(
                interval=interval,
                soc_kwh=soc_kwh,
                cheap_price=cheap_price,
            )
            decisions.append(decision)

        return decisions

    def _dispatch_interval(
        self,
        interval: IntervalInput,
        soc_kwh: float,
        cheap_price: float,
    ) -> tuple[DispatchDecision, float]:
        solar_kwh = interval.solar_kw * self.interval_hours
        load_kwh = interval.load_kw * self.interval_hours
        solar_to_load_kwh = min(solar_kwh, load_kwh)
        surplus_solar_kwh = solar_kwh - solar_to_load_kwh
        load_after_solar_kwh = load_kwh - solar_to_load_kwh

        solar_to_battery_kwh = 0.0
        battery_to_load_kwh = 0.0
        battery_power_kw = 0.0

        if surplus_solar_kwh > EPSILON:
            solar_to_battery_kwh, soc_kwh = self._charge_from_surplus(
                surplus_solar_kwh=surplus_solar_kwh,
                soc_kwh=soc_kwh,
            )
            curtailed_solar_kwh = surplus_solar_kwh - solar_to_battery_kwh
            grid_to_load_kwh = 0.0
            battery_power_kw = -solar_to_battery_kwh / self.interval_hours
        else:
            curtailed_solar_kwh = 0.0
            should_discharge = interval.grid_price_eur_per_kwh > cheap_price + EPSILON
            if should_discharge and load_after_solar_kwh > EPSILON:
                battery_to_load_kwh, soc_kwh = self._discharge_to_load(
                    load_after_solar_kwh=load_after_solar_kwh,
                    soc_kwh=soc_kwh,
                )
                battery_power_kw = battery_to_load_kwh / self.interval_hours
            grid_to_load_kwh = load_after_solar_kwh - battery_to_load_kwh

        return (
            DispatchDecision(
                timestamp=interval.timestamp,
                action=self._action_from_power(battery_power_kw),
                soc_kwh=self._zero_if_tiny(soc_kwh),
                battery_power_kw=self._zero_if_tiny(battery_power_kw),
                solar_to_load_kwh=self._zero_if_tiny(solar_to_load_kwh),
                solar_to_battery_kwh=self._zero_if_tiny(solar_to_battery_kwh),
                battery_to_load_kwh=self._zero_if_tiny(battery_to_load_kwh),
                grid_to_load_kwh=self._zero_if_tiny(grid_to_load_kwh),
                curtailed_solar_kwh=self._zero_if_tiny(curtailed_solar_kwh),
            ),
            soc_kwh,
        )

    def _charge_from_surplus(
        self,
        surplus_solar_kwh: float,
        soc_kwh: float,
    ) -> tuple[float, float]:
        max_by_power_kwh = self.battery.max_power_kw * self.interval_hours
        remaining_capacity_kwh = self.battery.max_soc_kwh - soc_kwh
        max_by_soc_kwh = remaining_capacity_kwh / self.battery.charge_efficiency
        charge_input_kwh = min(surplus_solar_kwh, max_by_power_kwh, max_by_soc_kwh)
        charge_input_kwh = max(0.0, charge_input_kwh)
        return charge_input_kwh, soc_kwh + (
            charge_input_kwh * self.battery.charge_efficiency
        )

    def _discharge_to_load(
        self,
        load_after_solar_kwh: float,
        soc_kwh: float,
    ) -> tuple[float, float]:
        max_by_power_kwh = self.battery.max_power_kw * self.interval_hours
        usable_soc_kwh = soc_kwh - self.battery.min_soc_kwh
        max_by_soc_kwh = usable_soc_kwh * self.battery.discharge_efficiency
        discharge_output_kwh = min(load_after_solar_kwh, max_by_power_kwh, max_by_soc_kwh)
        discharge_output_kwh = max(0.0, discharge_output_kwh)
        return discharge_output_kwh, soc_kwh - (
            discharge_output_kwh / self.battery.discharge_efficiency
        )

    @classmethod
    def _action_from_power(cls, battery_power_kw: float) -> str:
        if battery_power_kw < -EPSILON:
            return cls.CHARGE
        if battery_power_kw > EPSILON:
            return cls.DISCHARGE
        return cls.IDLE

    @staticmethod
    def _zero_if_tiny(value: float) -> float:
        return 0.0 if abs(value) < EPSILON else value
