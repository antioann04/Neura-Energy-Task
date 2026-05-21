"""Tests for the pure battery dispatch policy."""

from datetime import datetime, timedelta

from django.test import SimpleTestCase

from energy.domain import BatterySpec, GreedyDispatchPolicy, IntervalInput


START = datetime(2019, 7, 1)


def make_interval(
    index: int,
    *,
    solar_kw: float = 0.0,
    load_kw: float = 0.0,
    price: float = 0.30,
) -> IntervalInput:
    """Build deterministic 15-minute inputs for dispatch tests."""
    return IntervalInput(
        timestamp=START + timedelta(minutes=15 * index),
        solar_kw=solar_kw,
        load_kw=load_kw,
        grid_price_eur_per_kwh=price,
    )


class GreedyDispatchPolicyTests(SimpleTestCase):
    """Invariant and edge-case coverage for the greedy dispatch policy."""

    def setUp(self) -> None:
        self.battery = BatterySpec()
        self.policy = GreedyDispatchPolicy(self.battery)

    def assert_close(self, actual: float, expected: float, places: int = 7) -> None:
        """Keep numeric assertions readable around efficiency calculations."""
        self.assertAlmostEqual(actual, expected, places=places)

    def test_battery_defaults_match_pdf_constraints(self) -> None:
        self.assert_close(self.battery.capacity_kwh, 400.0)
        self.assert_close(self.battery.max_power_kw, 200.0)
        self.assert_close(self.battery.min_soc_kwh, 40.0)
        self.assert_close(self.battery.max_soc_kwh, 380.0)
        self.assert_close(
            self.battery.charge_efficiency * self.battery.discharge_efficiency,
            0.88,
        )

    def test_invalid_inputs_fail_fast(self) -> None:
        with self.assertRaises(ValueError):
            BatterySpec(capacity_kwh=0)
        with self.assertRaises(ValueError):
            BatterySpec(min_soc_fraction=0.95, max_soc_fraction=0.10)
        with self.assertRaises(ValueError):
            BatterySpec(round_trip_efficiency=1.2)
        with self.assertRaises(ValueError):
            IntervalInput(START, solar_kw=-1, load_kw=0, grid_price_eur_per_kwh=0.15)
        with self.assertRaises(ValueError):
            IntervalInput(START, solar_kw=0, load_kw=-1, grid_price_eur_per_kwh=0.15)
        with self.assertRaises(ValueError):
            GreedyDispatchPolicy(self.battery, initial_soc_fraction=0.99)

    def test_empty_week_returns_empty_schedule(self) -> None:
        self.assertEqual(self.policy.run_week([]), [])

    def test_surplus_solar_serves_load_then_charges_battery(self) -> None:
        decision = self.policy.run_week(
            [make_interval(0, solar_kw=200, load_kw=80, price=0.30)]
        )[0]

        expected_stored_kwh = 30.0 * self.battery.charge_efficiency
        self.assertEqual(decision.action, GreedyDispatchPolicy.CHARGE)
        self.assert_close(decision.solar_to_load_kwh, 20.0)
        self.assert_close(decision.solar_to_battery_kwh, 30.0)
        self.assert_close(decision.grid_to_load_kwh, 0.0)
        self.assert_close(decision.curtailed_solar_kwh, 0.0)
        self.assert_close(decision.battery_power_kw, -120.0)
        self.assert_close(decision.soc_kwh, self.battery.min_soc_kwh + expected_stored_kwh)

    def test_charge_power_cap_curtails_unusable_solar(self) -> None:
        decision = self.policy.run_week(
            [make_interval(0, solar_kw=1000, load_kw=0, price=0.30)]
        )[0]

        self.assertEqual(decision.action, GreedyDispatchPolicy.CHARGE)
        self.assert_close(decision.solar_to_battery_kwh, 50.0)
        self.assert_close(decision.curtailed_solar_kwh, 200.0)
        self.assert_close(decision.grid_to_load_kwh, 0.0)
        self.assert_close(decision.battery_power_kw, -200.0)

    def test_full_battery_curtails_surplus_without_exporting(self) -> None:
        full_policy = GreedyDispatchPolicy(
            self.battery,
            initial_soc_fraction=self.battery.max_soc_fraction,
        )
        decision = full_policy.run_week(
            [make_interval(0, solar_kw=200, load_kw=0, price=0.30)]
        )[0]

        self.assertEqual(decision.action, GreedyDispatchPolicy.IDLE)
        self.assert_close(decision.soc_kwh, self.battery.max_soc_kwh)
        self.assert_close(decision.solar_to_battery_kwh, 0.0)
        self.assert_close(decision.curtailed_solar_kwh, 50.0)
        self.assert_close(decision.grid_to_load_kwh, 0.0)

    def test_high_price_interval_discharges_after_solar(self) -> None:
        charged_policy = GreedyDispatchPolicy(self.battery, initial_soc_fraction=0.50)
        decisions = charged_policy.run_week(
            [
                make_interval(0, solar_kw=0, load_kw=0, price=0.15),
                make_interval(1, solar_kw=40, load_kw=200, price=0.30),
            ]
        )
        decision = decisions[1]

        self.assertEqual(decision.action, GreedyDispatchPolicy.DISCHARGE)
        self.assert_close(decision.solar_to_load_kwh, 10.0)
        self.assert_close(decision.battery_to_load_kwh, 40.0)
        self.assert_close(decision.grid_to_load_kwh, 0.0)
        self.assert_close(decision.battery_power_kw, 160.0)

    def test_cheapest_price_interval_does_not_discharge(self) -> None:
        charged_policy = GreedyDispatchPolicy(self.battery, initial_soc_fraction=0.50)
        decision = charged_policy.run_week(
            [make_interval(0, solar_kw=0, load_kw=100, price=0.15)]
        )[0]

        self.assertEqual(decision.action, GreedyDispatchPolicy.IDLE)
        self.assert_close(decision.battery_to_load_kwh, 0.0)
        self.assert_close(decision.grid_to_load_kwh, 25.0)
        self.assert_close(decision.soc_kwh, 200.0)

    def test_round_trip_efficiency_is_observable_across_one_cycle(self) -> None:
        decisions = self.policy.run_week(
            [
                make_interval(0, solar_kw=200, load_kw=0, price=0.15),
                make_interval(1, solar_kw=0, load_kw=200, price=0.30),
            ]
        )

        charged_from_solar_kwh = decisions[0].solar_to_battery_kwh
        delivered_to_load_kwh = decisions[1].battery_to_load_kwh
        self.assert_close(charged_from_solar_kwh, 50.0)
        self.assert_close(delivered_to_load_kwh / charged_from_solar_kwh, 0.88)
        self.assert_close(decisions[1].soc_kwh, self.battery.min_soc_kwh)

    def test_week_schedule_preserves_energy_and_limits(self) -> None:
        intervals = []
        for index in range(96 * 2):
            timestamp = START + timedelta(minutes=15 * index)
            price = 0.30 if 9 <= timestamp.hour < 23 else 0.15
            solar_kw = 200.0 if 11 <= timestamp.hour < 15 else 0.0
            load_kw = 120.0 if 9 <= timestamp.hour < 23 else 70.0
            intervals.append(
                IntervalInput(
                    timestamp=timestamp,
                    solar_kw=solar_kw,
                    load_kw=load_kw,
                    grid_price_eur_per_kwh=price,
                )
            )

        decisions = self.policy.run_week(intervals)
        self.assertEqual(len(decisions), len(intervals))
        self.assertTrue(any(d.action == GreedyDispatchPolicy.CHARGE for d in decisions))
        self.assertTrue(any(d.action == GreedyDispatchPolicy.DISCHARGE for d in decisions))

        max_interval_kwh = self.battery.max_power_kw * self.policy.interval_hours
        for source, decision in zip(intervals, decisions, strict=True):
            solar_kwh = source.solar_kw * self.policy.interval_hours
            load_kwh = source.load_kw * self.policy.interval_hours

            self.assertGreaterEqual(decision.soc_kwh, self.battery.min_soc_kwh - 1e-7)
            self.assertLessEqual(decision.soc_kwh, self.battery.max_soc_kwh + 1e-7)
            self.assertLessEqual(abs(decision.battery_power_kw), 200.0 + 1e-7)
            self.assertLessEqual(decision.solar_to_battery_kwh, max_interval_kwh + 1e-7)
            self.assertGreaterEqual(decision.grid_to_load_kwh, -1e-7)
            self.assertGreaterEqual(decision.curtailed_solar_kwh, -1e-7)
            self.assert_close(
                solar_kwh,
                decision.solar_to_load_kwh
                + decision.solar_to_battery_kwh
                + decision.curtailed_solar_kwh,
            )
            self.assert_close(
                load_kwh,
                decision.solar_to_load_kwh
                + decision.battery_to_load_kwh
                + decision.grid_to_load_kwh,
            )

    def test_non_increasing_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.policy.run_week(
                [
                    make_interval(1, solar_kw=0, load_kw=0, price=0.15),
                    make_interval(0, solar_kw=0, load_kw=0, price=0.15),
                ]
            )
