from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_hong_kong_taxi_dvrp_fleet.py")
SPEC = importlib.util.spec_from_file_location("build_hong_kong_taxi_dvrp_fleet", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


NETWORK = '''<?xml version="1.0" encoding="utf-8"?>
<network><nodes>
  <node id="a" x="0" y="0"/><node id="b" x="100" y="0"/><node id="c" x="50" y="100"/>
  <node id="dead" x="200" y="0"/><node id="x" x="1000" y="0"/><node id="y" x="1100" y="0"/>
</nodes><links>
  <link id="ab" from="a" to="b" length="100" permlanes="2" modes="car,bus"/>
  <link id="bc" from="b" to="c" length="120" permlanes="1" modes="car"/>
  <link id="ca" from="c" to="a" length="140" permlanes="1" modes="car"/>
  <link id="pt_only" from="a" to="b" length="100" permlanes="1" modes="pt,bus"/>
  <link id="traffic_signal_internal_connector_1" from="a" to="b" length="10" permlanes="1" modes="car"/>
  <link id="dead_spur" from="b" to="dead" length="100" permlanes="1" modes="car"/>
  <link id="dead_return" from="dead" to="b" length="100" permlanes="1" modes="car"/>
  <link id="xy" from="x" to="y" length="100" permlanes="1" modes="car"/>
  <link id="yx" from="y" to="x" length="100" permlanes="1" modes="car"/>
</links></network>
'''

PLANS = '''<?xml version="1.0" encoding="utf-8"?>
<population>
  <person id="p1"><plan selected="yes"><act type="home" link="ab"/><leg mode="taxi"/><act type="work" link="bc"/></plan></person>
  <person id="p2"><plan selected="yes"><act type="home" link="bc"/><leg mode="walk"/><act type="work" link="ca"/></plan></person>
  <person id="p3">
    <plan selected="no"><act type="home" link="ca"/><leg mode="taxi"/><act type="work" link="ab"/></plan>
    <plan selected="yes"><act type="home" link="bc"/><leg mode="taxi"/><act type="work" link="ca"/></plan>
  </person>
  <person id="p4"><plan selected="yes"><act type="home" link="unknown"/><leg mode="taxi"/><act type="work" link="ab"/></plan></person>
</population>
'''


class TaxiFleetBuilderTest(unittest.TestCase):
    def test_exact_full_fleet_apportionment_and_shift_contract(self):
        self.assertEqual(
            MODULE.apportion(MODULE.FULL_FLEET_SIZE, MODULE.TAXI_TYPE_TARGETS),
            {"urban": 13083, "nt": 2353, "lantau": 64},
        )
        starts, counts = MODULE.build_shift_starts(MODULE.FULL_FLEET_SIZE)
        self.assertEqual(len(starts), 15500)
        self.assertEqual(counts, {name: count for name, count, _a, _b in MODULE.SHIFT_TARGETS})
        self.assertEqual(starts.count(0.0), 3100)
        self.assertLess(max(starts), 10 * 3600)
        self.assertLessEqual(max(start + MODULE.SERVICE_SECONDS for start in starts), 28 * 3600)

    def test_full_fleet_generation_has_exact_types_and_service_duration(self):
        links = [
            MODULE.RoadLink("ab", "a", "b", 100, 2, 50, 0, frozenset({"car"}), {}),
            MODULE.RoadLink("bc", "b", "c", 120, 1, 75, 50, frozenset({"car"}), {}),
            MODULE.RoadLink("ca", "c", "a", 140, 1, 25, 50, frozenset({"car"}), {}),
        ]
        vehicles, audit = MODULE.build_fleet(links, {"ab": 20}, 15_500, 11)
        self.assertEqual(len(vehicles), 15_500)
        self.assertEqual(audit["taxi_type_counts"], {"urban": 13_083, "nt": 2_353, "lantau": 64})
        self.assertEqual(audit["sampling_source_counts"], {"origin_proxy": 10_850, "lane_km": 4_650})
        self.assertTrue(all(math.isclose(vehicle.service_end_s - vehicle.service_begin_s, 64_800) for vehicle in vehicles))

    def test_network_filter_proxy_mix_outputs_and_determinism(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            network = root / "network.xml.gz"
            with gzip.open(network, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(NETWORK)
            proxy = root / "proxy.csv"
            proxy.write_text("origin_tcs_zone,origin_link_id,origin_count\n1,ab,20\n2,unknown,10\n", encoding="utf-8")

            output1 = root / "one"
            output2 = root / "two"
            args1 = MODULE.parse_args([
                "--network", str(network), "--link-origin-proxy", str(proxy),
                "--output-dir", str(output1), "--fleet-size", "100", "--seed", "7",
            ])
            args2 = MODULE.parse_args([
                "--network", str(network), "--link-origin-proxy", str(proxy),
                "--output-dir", str(output2), "--fleet-size", "100", "--seed", "7",
            ])
            qa = MODULE.run(args1)
            MODULE.run(args2)

            self.assertEqual(qa["status"], "validated")
            self.assertEqual(qa["network_filter"]["signal_internal_links_excluded"], 1)
            self.assertEqual(qa["network_filter"]["dead_end_links_excluded"], 4)
            self.assertEqual(qa["network_filter"]["main_component_link_count"], 3)
            self.assertEqual(qa["network_filter"]["outside_main_component_link_count"], 0)
            self.assertEqual(qa["fleet"]["sampling_source_counts"], {"origin_proxy": 70, "lane_km": 30})
            self.assertEqual(sum(qa["fleet"]["taxi_type_counts"].values()), 100)

            with gzip.open(output1 / "hong_kong_taxi_fleet.xml.gz", "rb") as handle:
                vehicles = ET.parse(handle).getroot().findall("vehicle")
            self.assertEqual(len(vehicles), 100)
            self.assertTrue(all(vehicle.get("capacity") == "4" for vehicle in vehicles))
            self.assertTrue(all(vehicle.get("start_link") in {"ab", "bc", "ca"} for vehicle in vehicles))
            self.assertEqual(vehicles[0].get("id"), "hk_taxi_urban_00001")

            with (output1 / "hong_kong_taxi_nactive_15min.csv").open(encoding="utf-8", newline="") as handle:
                active = list(csv.DictReader(handle))
            self.assertEqual(len(active), 96)
            self.assertEqual(int(active[0]["active_at_start"]), 20)

            self.assertEqual(
                (output1 / "hong_kong_taxi_fleet.xml.gz").read_bytes(),
                (output2 / "hong_kong_taxi_fleet.xml.gz").read_bytes(),
            )
            starts1 = (output1 / "hong_kong_taxi_start_links.csv").read_bytes()
            starts2 = (output2 / "hong_kong_taxi_start_links.csv").read_bytes()
            self.assertEqual(starts1, starts2)
            saved_qa = json.loads((output1 / "hong_kong_taxi_fleet_qa.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_qa["failed_checks"], [])

    def test_missing_proxy_uses_explicit_lane_km_fallback(self):
        self.assertEqual(MODULE.load_origin_proxy(None, {"ab"})[1]["status"], "not_provided_lane_km_fallback")

    def test_frozen_selected_plans_stream_to_link_prior(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plans = root / "experienced_plans.xml.gz"
            with gzip.open(plans, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(PLANS)
            weights, audit = MODULE.load_taxi_origin_plans(plans, {"ab", "bc", "ca"})
            plans_zst = root / "experienced_plans.xml.zst"
            plans_zst.write_bytes(MODULE.zstandard.ZstdCompressor().compress(PLANS.encode("utf-8")))
            zst_weights, zst_audit = MODULE.load_taxi_origin_plans(plans_zst, {"ab", "bc", "ca"})
        self.assertEqual(weights, {"ab": 1.0, "bc": 1.0})
        self.assertEqual(zst_weights, weights)
        self.assertEqual(audit["persons"], 4)
        self.assertEqual(zst_audit["persons"], 4)
        self.assertEqual(audit["selected_taxi_legs"], 3)
        self.assertEqual(audit["ineligible_origin_link_legs"], 1)


if __name__ == "__main__":
    unittest.main()
