"""Application services for data ingestion, dispatch, and reporting.

This module contains orchestration classes that may talk to the database,
Renewables.ninja, pandas, and plotting code. The domain policy itself stays in
energy.domain so it can be tested without Django.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from io import StringIO
from math import exp
import os
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from matplotlib.figure import Figure
import pandas as pd
import requests

from energy.domain import (
    BatterySpec,
    DispatchDecision,
    GreedyDispatchPolicy,
    IntervalInput,
)
from energy.models import DispatchInterval, EnergyInterval


INTERVAL_HOURS = 0.25
DAY_PRICE_EUR_PER_KWH = 0.30
NIGHT_PRICE_EUR_PER_KWH = 0.15
DAY_START_HOUR = 9
DAY_END_HOUR = 23


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
    dataset: str = "merra2"


class RenewablesNinjaClient:
    """Fetch hourly Limassol PV production from Renewables.ninja."""

    api_url = "https://www.renewables.ninja/api/data/pv"

    def __init__(
        self,
        api_token: str | None = None,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        """Create an API client, optionally with an injected session for tests."""
        self.api_token = api_token or os.getenv("RENEWABLES_NINJA_API_TOKEN", "")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def fetch_hourly_pv(self, request: SolarRequest) -> pd.Series:
        """Call Renewables.ninja and return hourly PV output in kW."""
        response = self.session.get(
            self.api_url,
            params={
                "lat": request.latitude,
                "lon": request.longitude,
                "date_from": request.start_date.isoformat(),
                "date_to": request.end_date.isoformat(),
                "dataset": request.dataset,
                "capacity": request.capacity_kw,
                "system_loss": request.system_loss,
                "tracking": 0,
                "tilt": request.tilt,
                "azim": request.azimuth,
                "format": "json",
            },
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {})
        if not data:
            raise RuntimeError("Renewables.ninja returned no PV data.")

        # The API returns epoch-millisecond keys. Sorting makes the downstream
        # resampling deterministic even if the JSON object order ever changes.
        rows = [
            (
                pd.to_datetime(int(timestamp_ms), unit="ms", utc=True),
                float(values["electricity"]),
            )
            for timestamp_ms, values in data.items()
        ]
        rows.sort(key=lambda row: row[0])
        series = pd.Series(
            data=[value for _, value in rows],
            index=pd.DatetimeIndex([timestamp for timestamp, _ in rows]),
            name="solar_kw",
            dtype="float64",
        )
        return series

    def _headers(self) -> dict[str, str]:
        """Return token auth headers when a real token is configured."""
        token = self.api_token.strip()
        if not token or token == "replace_me":
            return {}
        return {"Authorization": f"Token {token}"}


class WeeklyInputBuilder:
    """Build and persist the three required 15-minute input series."""

    def __init__(
        self,
        solar_request: SolarRequest | None = None,
        client: RenewablesNinjaClient | None = None,
        timezone_name: str | None = None,
    ) -> None:
        """Create the weekly builder for a specific solar request and timezone."""
        self.solar_request = solar_request or SolarRequest()
        self.client = client or RenewablesNinjaClient()
        self.timezone_name = timezone_name or settings.TIME_ZONE
        self.local_tz = ZoneInfo(self.timezone_name)

    def build_solar_series(self) -> pd.Series:
        """Fetch hourly PV and repeat each hour into four 15-minute values.

        Renewables.ninja returns hourly average kW values. Repeating each hourly
        value at :00, :15, :30, and :45 preserves the hourly energy exactly:
        1 hour * kW == 4 * 0.25 hours * the same kW.
        """
        api_request = replace(
            self.solar_request,
            start_date=self.solar_request.start_date - timedelta(days=1),
        )
        hourly_utc = self.client.fetch_hourly_pv(api_request)
        timestamps: list[pd.Timestamp] = []
        values: list[float] = []

        for timestamp_utc, solar_kw in hourly_utc.items():
            for step in range(4):
                timestamp = timestamp_utc + pd.Timedelta(minutes=15 * step)
                timestamps.append(timestamp.tz_convert(self.local_tz))
                values.append(float(solar_kw))

        series = pd.Series(
            data=values,
            index=pd.DatetimeIndex(timestamps),
            name="solar_kw",
            dtype="float64",
        ).sort_index()
        return self._filter_to_local_week(series)

    def build_load_series(self, index: pd.DatetimeIndex | None = None) -> pd.Series:
        """Generate a defensible hotel load shape with a 200 kW weekly peak."""
        timestamps = index if index is not None else self._default_local_index()
        raw_load = [
            self._raw_hotel_load_kw(timestamp.to_pydatetime())
            for timestamp in timestamps
        ]
        peak = max(raw_load)
        if peak <= 0:
            raise RuntimeError("Synthetic hotel load profile produced no demand.")

        scale = 200.0 / peak
        return pd.Series(
            data=[value * scale for value in raw_load],
            index=timestamps,
            name="load_kw",
            dtype="float64",
        )

    def build_tariff_series(self, index: pd.DatetimeIndex | None = None) -> pd.Series:
        """Generate the day/night TOU price series from the PDF."""
        timestamps = index if index is not None else self._default_local_index()
        return pd.Series(
            data=[
                DAY_PRICE_EUR_PER_KWH
                if DAY_START_HOUR <= timestamp.hour < DAY_END_HOUR
                else NIGHT_PRICE_EUR_PER_KWH
                for timestamp in timestamps
            ],
            index=timestamps,
            name="grid_price_eur_per_kwh",
            dtype="float64",
        )

    def build_input_frame(self) -> pd.DataFrame:
        """Return the aligned solar, load, and tariff series for the week."""
        solar = self.build_solar_series()
        load = self.build_load_series(solar.index)
        tariff = self.build_tariff_series(solar.index)
        frame = pd.concat([solar, load, tariff], axis=1)
        if frame.isna().any().any():
            raise RuntimeError("Input series are not aligned.")
        return frame

    def seed_database(self) -> int:
        """Write the representative week into EnergyInterval rows."""
        frame = self.build_input_frame()
        rows = [
            EnergyInterval(
                timestamp=timestamp.to_pydatetime(),
                solar_kw=float(record.solar_kw),
                load_kw=float(record.load_kw),
                grid_price_eur_per_kwh=float(record.grid_price_eur_per_kwh),
            )
            for timestamp, record in frame.iterrows()
        ]

        with transaction.atomic():
            # Seeding is intentionally idempotent: one command rerun replaces
            # both inputs and dependent dispatch rows as a single transaction.
            DispatchInterval.objects.all().delete()
            EnergyInterval.objects.all().delete()
            EnergyInterval.objects.bulk_create(rows)

        return len(rows)

    def _default_local_index(self) -> pd.DatetimeIndex:
        """Return the exact 672 local 15-minute timestamps for the target week."""
        start = datetime.combine(self.solar_request.start_date, time.min).replace(
            tzinfo=self.local_tz
        )
        end = datetime.combine(
            self.solar_request.end_date + timedelta(days=1),
            time.min,
        ).replace(tzinfo=self.local_tz)
        return pd.date_range(start=start, end=end, freq="15min", inclusive="left")

    def _filter_to_local_week(self, series: pd.Series) -> pd.Series:
        """Trim UTC-origin PV data to the requested Cyprus local calendar week."""
        expected_index = self._default_local_index()
        filtered = series[
            (series.index >= expected_index[0]) & (series.index <= expected_index[-1])
        ]
        if len(filtered) != len(expected_index):
            raise RuntimeError(
                "Solar series does not cover the requested local representative week."
            )
        return filtered

    def _raw_hotel_load_kw(self, timestamp: datetime) -> float:
        """Return the unscaled synthetic hotel load for one local timestamp."""
        local_timestamp = timestamp.astimezone(self.local_tz)
        hour = local_timestamp.hour + (local_timestamp.minute / 60)
        weekend_multiplier = 1.07 if local_timestamp.weekday() in {4, 5, 6} else 1.0

        # Shape assumptions: hotel baseload overnight, breakfast activity,
        # modest lunch service, cooling peak later in the afternoon, and an
        # evening occupancy bump. build_load_series scales this to a 200 kW peak.
        overnight_baseload = 45.0
        guest_morning = self._bell_curve(hour, center=8.0, width=2.0, amplitude=18.0)
        kitchen_lunch = self._bell_curve(hour, center=13.0, width=2.0, amplitude=8.0)
        cooling_peak = self._bell_curve(hour, center=17.5, width=2.3, amplitude=92.0)
        evening_occupancy = self._bell_curve(hour, center=20.5, width=2.4, amplitude=42.0)
        operations = 8.0 if 7 <= hour < 24 else 4.0

        return (
            overnight_baseload
            + operations
            + guest_morning
            + kitchen_lunch
            + cooling_peak
            + evening_occupancy
        ) * weekend_multiplier

    @staticmethod
    def _bell_curve(hour: float, *, center: float, width: float, amplitude: float) -> float:
        """Produce a smooth daily load bump around a center hour."""
        distance = min(abs(hour - center), 24 - abs(hour - center))
        return amplitude * exp(-((distance / width) ** 2))


class DispatchService:
    """Run the dispatch policy and persist DispatchInterval rows."""

    def __init__(self, policy: GreedyDispatchPolicy | None = None) -> None:
        """Create the service with the default greedy policy or a test double."""
        self.policy = policy or GreedyDispatchPolicy(BatterySpec())

    def run_and_store(self) -> list[DispatchDecision]:
        """Read EnergyInterval rows, run policy, and store dispatch decisions."""
        intervals = list(EnergyInterval.objects.order_by("timestamp"))
        inputs = [
            IntervalInput(
                timestamp=interval.timestamp,
                solar_kw=interval.solar_kw,
                load_kw=interval.load_kw,
                grid_price_eur_per_kwh=interval.grid_price_eur_per_kwh,
            )
            for interval in intervals
        ]
        decisions = self.policy.run_week(inputs)
        dispatch_rows = [
            DispatchInterval(
                interval=interval,
                action=decision.action,
                soc_kwh=decision.soc_kwh,
                battery_power_kw=decision.battery_power_kw,
                solar_to_load_kwh=decision.solar_to_load_kwh,
                solar_to_battery_kwh=decision.solar_to_battery_kwh,
                battery_to_load_kwh=decision.battery_to_load_kwh,
                grid_to_load_kwh=decision.grid_to_load_kwh,
                curtailed_solar_kwh=decision.curtailed_solar_kwh,
            )
            for interval, decision in zip(intervals, decisions, strict=True)
        ]

        with transaction.atomic():
            # Avoid per-row update_or_create loops; this weekly batch is tiny,
            # but bulk replacement keeps the command simple and repeatable.
            DispatchInterval.objects.all().delete()
            DispatchInterval.objects.bulk_create(dispatch_rows)

        return decisions


class WeeklyReportService:
    """Compute the numbers required by /reports/weekly/."""

    def __init__(self, battery: BatterySpec | None = None) -> None:
        """Create the report service with the battery spec used for SoC percent."""
        self.battery = battery or BatterySpec()

    def build_context(self) -> dict[str, object]:
        """Return spend, savings, kWh totals, self-consumption, and SoC chart data."""
        intervals = list(
            EnergyInterval.objects.select_related("dispatch").order_by("timestamp")
        )
        if not intervals:
            return {
                "has_data": False,
                "message": "No interval data found. Run python manage.py seed_week first.",
            }

        dispatch_rows = []
        no_battery_spend = 0.0
        battery_spend = 0.0
        charged_kwh = 0.0
        discharged_kwh = 0.0
        total_pv_kwh = 0.0
        curtailed_kwh = 0.0
        soc_points: list[dict[str, Any]] = []
        chart_timestamps: list[datetime] = []
        chart_soc_percent: list[float] = []

        # select_related above keeps this loop from doing one query per interval.
        for interval in intervals:
            try:
                dispatch = interval.dispatch
            except DispatchInterval.DoesNotExist as exc:
                raise RuntimeError("Dispatch data missing. Run python manage.py seed_week.") from exc

            interval_solar_kwh = interval.solar_kw * INTERVAL_HOURS
            interval_load_kwh = interval.load_kw * INTERVAL_HOURS
            no_battery_grid_kwh = max(0.0, interval_load_kwh - interval_solar_kwh)
            price = interval.grid_price_eur_per_kwh
            local_timestamp = timezone.localtime(interval.timestamp)
            soc_percent = 100 * dispatch.soc_kwh / self.battery.capacity_kwh

            no_battery_spend += no_battery_grid_kwh * price
            battery_spend += dispatch.grid_to_load_kwh * price
            charged_kwh += dispatch.solar_to_battery_kwh
            discharged_kwh += dispatch.battery_to_load_kwh
            total_pv_kwh += interval_solar_kwh
            curtailed_kwh += dispatch.curtailed_solar_kwh
            chart_timestamps.append(local_timestamp)
            chart_soc_percent.append(soc_percent)
            soc_points.append(
                {
                    "timestamp": local_timestamp.isoformat(),
                    "soc_kwh": dispatch.soc_kwh,
                    "soc_percent": soc_percent,
                }
            )
            dispatch_rows.append(
                {
                    "timestamp": local_timestamp,
                    "solar_kw": interval.solar_kw,
                    "load_kw": interval.load_kw,
                    "price": price,
                    "action": dispatch.action,
                    "battery_power_kw": dispatch.battery_power_kw,
                    "soc_kwh": dispatch.soc_kwh,
                    "soc_percent": soc_percent,
                    "grid_to_load_kwh": dispatch.grid_to_load_kwh,
                    "curtailed_solar_kwh": dispatch.curtailed_solar_kwh,
                }
            )

        solar_self_consumption_pct = (
            100 * (total_pv_kwh - curtailed_kwh) / total_pv_kwh
            if total_pv_kwh > 0
            else 0.0
        )

        return {
            "has_data": True,
            "period_start": dispatch_rows[0]["timestamp"],
            "period_end": dispatch_rows[-1]["timestamp"],
            "interval_count": len(dispatch_rows),
            "grid_spend_with_battery": battery_spend,
            "grid_spend_without_battery": no_battery_spend,
            "savings": no_battery_spend - battery_spend,
            "charged_kwh": charged_kwh,
            "discharged_kwh": discharged_kwh,
            "total_pv_kwh": total_pv_kwh,
            "curtailed_solar_kwh": curtailed_kwh,
            "solar_self_consumption_pct": solar_self_consumption_pct,
            "soc_points": soc_points,
            "soc_chart_svg": self._build_soc_chart_svg(
                chart_timestamps,
                chart_soc_percent,
            ),
            "dispatch_rows": dispatch_rows,
        }

    def _build_soc_chart_svg(
        self,
        timestamps: list[datetime],
        soc_percent: list[float],
    ) -> str:
        """Render the SoC curve as inline SVG for the Django template."""
        figure = Figure(figsize=(10, 3.2), dpi=120)
        axis = figure.subplots()
        axis.plot(timestamps, soc_percent, color="#2166ac", linewidth=1.8)
        axis.set_title("Battery state of charge")
        axis.set_ylabel("SoC (%)")
        axis.set_ylim(0, 100)
        axis.grid(True, color="#d7dde2", linewidth=0.7)
        figure.autofmt_xdate()

        buffer = StringIO()
        figure.savefig(buffer, format="svg", bbox_inches="tight")
        return buffer.getvalue()
