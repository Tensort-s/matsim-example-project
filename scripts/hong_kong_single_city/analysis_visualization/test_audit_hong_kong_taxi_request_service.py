from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from audit_hong_kong_taxi_request_service import audit


class TaxiRequestServiceAuditTest(unittest.TestCase):
    def test_request_conservation_waits_and_blackout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "requests.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "request_id", "person_ids", "operational_only",
                        "submitted_s", "picked_up_s", "dropped_off_s", "wait_s",
                        "vehicle_id", "status", "rejection_cause", "horizon_s",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "request_id": "a", "person_ids": "p", "operational_only": "false",
                    "submitted_s": "3600", "picked_up_s": "3660",
                    "dropped_off_s": "3900", "wait_s": "60", "vehicle_id": "v",
                    "status": "completed", "rejection_cause": "", "horizon_s": "108000",
                })
                writer.writerow({
                    "request_id": "b", "person_ids": "s", "operational_only": "true",
                    "submitted_s": "7200", "picked_up_s": "", "dropped_off_s": "",
                    "wait_s": "100800", "vehicle_id": "", "status": "waiting",
                    "rejection_cause": "", "horizon_s": "108000",
                })

            result = audit(source)
            self.assertTrue(result["request_conservation"])
            self.assertEqual(2, result["submitted"])
            self.assertEqual(1, result["picked"])
            self.assertEqual(0.5, result["not_picked_share"])
            self.assertEqual(60.0, result["completed_wait"]["mean_s"])
            self.assertEqual([2], result["pickup_blackout_hours"])


if __name__ == "__main__":
    unittest.main()
