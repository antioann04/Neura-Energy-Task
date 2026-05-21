# Neura Energy Take-Home: Behind-the-Meter Battery Dispatch

This project is a small Django service for running behind-the-meter (BTM) battery dispatch for a commercial customer in Cyprus, as part of the Neura Energy take-home task.

## Setup Instructions

**Prerequisites:** Python 3.11+
We recommend using a virtual environment (e.g., `venv` or `conda`).

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **The "One-Command" Run Flow:**
   To setup the database, seed the representative week data (which fetches PV from the Renewables.ninja API, synthesizes the hotel load, calculates the dispatch, and persists everything to SQLite), and start the server, simply run:
   ```bash
   python manage.py migrate
   python manage.py seed_week
   python manage.py runserver
   ```

3. **View the Report:**
   Open your browser and navigate to: http://127.0.0.1:8000/reports/weekly/

## Data Sources & Assumptions

- **Solar (Renewables.ninja):** We extracted 1 week of Limassol data for a 200 kWp system via the Renewables.ninja API.
  - *Resampling Method:* The API provides hourly average power (kW). We mapped this to 15-minute intervals by repeating the hourly value 4 times. Since 1h * X kW = 4 * 0.25h * X kW, the total energy (kWh) is perfectly conserved without interpolation skew.
- **Hotel Load:** Because no clean public 15-minute dataset exists for a Cyprus hotel, we synthesized a defensible one.
  - *Assumptions:* The baseline load includes a 45 kW overnight hotel baseload and operational baseline. We layered four Gaussian "bell curves" over the day representing guest morning wake-ups, kitchen lunch prep, a massive afternoon cooling spike, and an evening occupancy bump. Weekends received a 1.07x multiplier. Finally, the entire weekly curve was scaled so the absolute peak hits exactly 200 kW.
- **Grid Tariff:** We modeled the 2-rate TOU on EAC's residential Code 02 pattern (Day 09:00–23:00 at €0.30/kWh; Night 23:00–09:00 at €0.15/kWh). 

## Dispatch Policy Assumptions

The logic relies on a **Greedy Approach** and runs independently of Django (pure OOP Python in `energy/domain.py`) to keep architectural boundaries clean.
- Solar covers the load first.
- Surplus solar charges the battery (up to 95% SoC, 200 kW max). We factored a symmetric ~93.8% one-way efficiency to equate to the 88% round-trip real-world LFP loss limit.
- If solar is insufficient and we are inside the expensive **Day rate (€0.30)** window, the battery discharges to cover the load (down to 10% SoC minimum).
- Zero grid export: Any surplus solar that cannot be absorbed locally is curtailed.

## AI Usage (Copilot / Codex / ChatGPT)

I engaged AI using a strict "Senior driving a Junior" methodology. 

- **Workflow:** 
  1. I explicitly instructed the AI *not* to write code right away, but to act as a subordinate taking architectural directions.
  2. I forced the AI to break down the PDF, list required tools, design an OOP file structure, and define responsibilities for each module to prevent monolithic "god-files".
  3. We followed an iterative, Test-Driven Development (TDD) approach—building, testing, and validating components one by one before proceeding.
- **Where it helped:** Generating the heavy math for the load's Gaussian bell curves, dealing with the localized timezones/pandas resampling, and stubbing out boilerplate test structure.
- **Where it got in the way:** Nowhere. I believe that with the right guiding hand AI can do everything without mistakes.

## What We Would Build Next (With Another Day)

- **Machine Learning & Predictive Optimization:** Learn from the historical energy and weather data using an AI model to detect seasonal anomalies. We could utilize these predictions to give predictive suggestions (or fully automate dispatch) on how to use the battery and energy for absolutely optimal savings, rather than relying on a purely greedy reactive dispatch.
- **Optimization Solver:** Replace the deterministic greedy algorithm with a Linear Programming solver (e.g., `PuLP` or `SciPy`) to optimize dispatch via perfect forecasting—immensely useful if adding peak-shaving demand charges.
- **Live PDF Scraping:** Actually build a parser to dynamically download and extract the real EAC commercial tariff from their website.
- **Interactive Frontend:** Upgrade the static weekly report view into a dynamic React or Vue dashboard possessing a "What-If" capacity suite to vary PV and Battery sizes on the fly.

## Time Constraints
*Note: I kept it lean and heavily AI-driven, took a small break for something I had to do in the middle and still finished in 1-1.1/2 hour.
