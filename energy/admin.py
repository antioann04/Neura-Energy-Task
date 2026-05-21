"""Admin registrations for inspecting seeded intervals and dispatch output."""

from django.contrib import admin

from energy.models import DispatchInterval, EnergyInterval


@admin.register(EnergyInterval)
class EnergyIntervalAdmin(admin.ModelAdmin):
    """Read-friendly admin table for the 15-minute input series."""

    list_display = ("timestamp", "solar_kw", "load_kw", "grid_price_eur_per_kwh")
    ordering = ("timestamp",)


@admin.register(DispatchInterval)
class DispatchIntervalAdmin(admin.ModelAdmin):
    """Read-friendly admin table for dispatch decisions and SoC."""

    list_display = (
        "interval",
        "action",
        "soc_kwh",
        "battery_power_kw",
        "grid_to_load_kwh",
        "curtailed_solar_kwh",
    )
    ordering = ("interval__timestamp",)
