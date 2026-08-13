import gzip
import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("audit_hong_kong_traffic_signal_run.py")
SPEC = importlib.util.spec_from_file_location("traffic_signal_runtime_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TrafficSignalRuntimeAuditTests(unittest.TestCase):

    def test_vehicle_classes_are_separated(self):
        cases = {
            "hk_vehicle_123": "private_car",
            "HK_VEHICLE_456": "private_car",
            "veh_dep_bus_12": "bus",
            "veh_dep_gmb_34": "gmb",
            "school_bus_vehicle_56": "school_bus",
            "freight_vehicle_78": "other_road_vehicle",
        }
        for vehicle, expected in cases.items():
            with self.subTest(vehicle=vehicle):
                self.assertEqual(MODULE.classify_vehicle(vehicle), expected)

    def test_basic_counts_support_gzip_and_controlled_link_filter(self):
        xml = b"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
<events>
  <event time=\"1\" type=\"entered link\" vehicle=\"hk_vehicle_1\" link=\"a\" />
  <event time=\"2\" type=\"entered link\" vehicle=\"veh_dep_bus_1\" link=\"a\" />
  <event time=\"3\" type=\"entered link\" vehicle=\"veh_dep_gmb_1\" link=\"b\" />
  <event time=\"4\" type=\"stuckAndAbort\" person=\"p1\" />
</events>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.xml.gz"
            with gzip.open(path, "wb") as stream:
                stream.write(xml)
            event_types, entries, entries_by_class = MODULE.basic_event_counts(
                path, {"a"}
            )

        self.assertEqual(event_types["entered link"], 3)
        self.assertEqual(event_types["stuckAndAbort"], 1)
        self.assertEqual(entries, {"a": 2})
        self.assertEqual(entries_by_class, {"private_car": 1, "bus": 1})

    def test_bisect_finds_same_or_next_transition(self):
        transition_times = [3.0, 63.0, 123.0]
        self.assertEqual(MODULE.bisect_left(transition_times, 63.0), 1)
        self.assertEqual(MODULE.bisect_left(transition_times, 64.0), 2)
        self.assertEqual(MODULE.bisect_left(transition_times, 124.0), 3)


if __name__ == "__main__":
    unittest.main()
