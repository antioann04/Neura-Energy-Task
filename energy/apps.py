"""Django app configuration for the energy domain."""

from django.apps import AppConfig


class EnergyConfig(AppConfig):
    """Register the energy app with Django."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "energy"
