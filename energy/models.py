"""Database models for time-series inputs and dispatch results.

The PDF asks us to store solar, load, and tariff data in the database instead
of hardcoding them in views.py. The models below keep that contract explicit.
"""

from django.db import models


class EnergyInterval(models.Model):
    """One 15-minute input interval for the representative hotel week."""

    timestamp = models.DateTimeField(unique=True)
    solar_kw = models.FloatField()
    load_kw = models.FloatField()
    grid_price_eur_per_kwh = models.FloatField()

    class Meta:
        ordering = ["timestamp"]

    def __str__(self) -> str:
        return f"{self.timestamp}: solar={self.solar_kw:.1f} kW load={self.load_kw:.1f} kW"


class DispatchInterval(models.Model):
    """Battery dispatch decision and energy accounting for one input interval."""

    class Action(models.TextChoices):
        CHARGE = "charge", "Charge"
        DISCHARGE = "discharge", "Discharge"
        IDLE = "idle", "Idle"

    interval = models.OneToOneField(
        EnergyInterval,
        on_delete=models.CASCADE,
        related_name="dispatch",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    soc_kwh = models.FloatField()
    battery_power_kw = models.FloatField(
        help_text="Positive when discharging, negative when charging."
    )
    solar_to_load_kwh = models.FloatField()
    solar_to_battery_kwh = models.FloatField()
    battery_to_load_kwh = models.FloatField()
    grid_to_load_kwh = models.FloatField()
    curtailed_solar_kwh = models.FloatField()

    class Meta:
        ordering = ["interval__timestamp"]

    def __str__(self) -> str:
        return f"{self.interval.timestamp}: {self.action} at SoC {self.soc_kwh:.1f} kWh"
