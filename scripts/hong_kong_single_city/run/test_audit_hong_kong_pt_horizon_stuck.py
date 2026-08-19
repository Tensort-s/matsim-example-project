from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from audit_hong_kong_pt_horizon_stuck import (
    attributes,
    classify,
    read_driver_starts,
)


class PtHorizonStuckAuditTest(unittest.TestCase):
    def test_attributes_and_boundary_classification(self) -> None:
        event = attributes(
            '<event time="108000.0" type="stuckAndAbort" person="driver" '
            'link="road" legMode="car" />'
        )
        starts = {
            "driver": {
                "driverId": "driver",
                "vehicleId": "vehicle",
                "departureId": "departure__day2",
            }
        }
        schedule = {
            "departure__day2": {
                "line_id": "line_bus",
                "route_id": "bus_route",
                "departure_time_s": 107000.0,
                "route_duration_s": 2000.0,
                "scheduled_end_s": 109000.0,
            }
        }
        summary, rows = classify([event], starts, schedule, 108000.0)
        self.assertEqual(1, summary["road_day2_events"])
        self.assertEqual(1, summary["day2_scheduled_end_after_horizon"])
        self.assertTrue(summary["all_at_exact_horizon"])
        self.assertEqual("bus", rows[0]["submode"])

    def test_driver_start_uses_last_departure_for_reused_driver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "starts.xmlfrag"
            path.write_text(
                '<event type="TransitDriverStarts" driverId="d" departureId="x" />\n'
                '<event type="TransitDriverStarts" driverId="d" departureId="y" />\n',
                encoding="utf-8",
            )
            self.assertEqual("y", read_driver_starts(path)["d"]["departureId"])


if __name__ == "__main__":
    unittest.main()
