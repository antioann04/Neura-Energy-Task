# Neura Energy Take-Home

Small Django service for the behind-the-meter battery dispatch task.

## Current Scaffold

The project is intentionally compact:

- `neura_energy/` contains Django project settings and top-level routing.
- `energy/models.py` stores the required 15-minute input series and dispatch output.
- `energy/domain.py` will contain the pure OOP dispatch policy and battery objects.
- `energy/services.py` will orchestrate Renewables.ninja data, generated load, tariff data, dispatch, and report calculations.
- `energy/views.py` stays thin and renders `/reports/weekly/`.
- `energy/management/commands/seed_week.py` will build the representative week and compute dispatch.
- `energy/tests/` will hold dispatch invariant tests and report calculation tests.
- `data/` will hold non-secret generated or cached data artifacts.

## Task Requirements To Implement

- Pull 200 kW Limassol PV data from Renewables.ninja.
- Resample hourly PV to 15-minute intervals and document the method.
- Generate a defensible hotel load profile with a weekly peak near 200 kW.
- Generate the stylised two-rate TOU tariff.
- Store all input series in SQLite.
- Dispatch a 400 kWh / 200 kW battery with 10%-95% SoC limits, 88% round-trip efficiency, and no grid export.
- Render a weekly report with spend, counterfactual spend, savings, charged/discharged kWh, self-consumption, and SoC curve.
