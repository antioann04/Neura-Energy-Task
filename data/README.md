# Data Directory

This directory holds generated artifacts for the take-home task.

**Current Architecture:**
Instead of hardcoding or storing raw CSV files, we extract live 1-hour PV data from the `Renewables.ninja` API during the `python manage.py seed_week` command.

The fetch dynamically resamples the data to 15-minute intervals, synthesizes a matched hotel load profile, applies the day/night tariff, calculates the battery dispatch, and stores it directly into the SQLite database. 

*No static CSVs are required to run this solution.*
