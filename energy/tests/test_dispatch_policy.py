"""Tests to add for the pure dispatch policy.

Planned coverage:
- SoC never drops below 10% or rises above 95%.
- Charge/discharge power never exceeds 200 kW.
- No grid export is produced.
- Solar first serves load, then charges battery, then curtails.
- Day-rate periods discharge when load remains after solar.
"""
