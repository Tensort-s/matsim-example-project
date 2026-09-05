#!/usr/bin/env python3
"""Focused tests for the unified Hong Kong parking-supply builder."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_hong_kong_parking_supply import (
    hourly_rates,
    meter_rules,
    sha256_file,
    td_government_charge_rules,
)


class ParkingSupplyBuilderTest(unittest.TestCase):
    def test_sha256_file_is_reproducible(self) -> None:
        source = Path(__file__)
        self.assertEqual(64, len(sha256_file(source)))
        self.assertEqual(sha256_file(source), sha256_file(source))

    def test_meter_rule_expands_split_day_groups(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "OperatingPeriod": "3D",
                    "TimeUnit": 15,
                    "PaymentUnit": 4.0,
                    "LPP": 30,
                }
            ]
        )
        rules = meter_rules(frame)
        self.assertEqual(2, len(rules))
        self.assertEqual({"08:00", "10:00"}, {rule["period_start"] for rule in rules})
        self.assertEqual({16.0}, {rule["equivalent_hourly_rate_hkd"] for rule in rules})
        self.assertEqual({30}, {rule["maximum_stay_min"] for rule in rules})

    def test_half_hourly_rate_is_normalized(self) -> None:
        self.assertEqual(
            [32.0, 20.0],
            hourly_rates(
                [
                    {"type": "half-hourly", "price": 16},
                    {"type": "hourly", "price": 20},
                ]
            ),
        )

    def test_td_combined_day_passes_are_structured(self) -> None:
        rules = td_government_charge_rules(
            "Hourly charge for private cars / vans (07:00 - 19:00) ($)",
            "210 (Day Park 07:00 - 19:00, Mon - Sat, except PH) "
            "150 (Day Park 08:00 - 00:00, Sun & PH)",
        )
        self.assertEqual(2, len(rules))
        self.assertEqual([210.0, 150.0], [rule["price_hkd"] for rule in rules])
        self.assertEqual(
            ["Mon - Sat, except PH", "Sun & PH"],
            [rule["eligibility_text"] for rule in rules],
        )


if __name__ == "__main__":
    unittest.main()
