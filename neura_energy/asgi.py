"""ASGI entry point for Django."""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "neura_energy.settings")

application = get_asgi_application()
