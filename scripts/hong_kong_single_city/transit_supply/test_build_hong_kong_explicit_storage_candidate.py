from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_build_hong_kong_road_continuity_candidate import (
    RoadContinuityCandidateTest,
)


SCRIPT = Path(__file__).with_name("build_hong_kong_explicit_storage_candidate.py")


class ExplicitStorageCandidateTest(unittest.TestCase):
    def test_network_is_byte_identical_and_x_is_lower_bound(self) -> None:
        helper = RoadContinuityCandidateTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network, hotspots, neighbors = helper.prepare(root)
            output = root / "candidate2"
            subprocess.run([
                sys.executable, str(SCRIPT),
                "--input-network", str(network),
                "--hotspot-links", str(hotspots),
                "--hotspot-neighbors", str(neighbors),
                "--output-dir", str(output),
                "--expected-candidate-relationships", "3",
                "--expected-unique-links", "2",
            ], check=True, capture_output=True, text=True)
            copied = output / "network_tpdm3_physical_explicit_storage_v2.xml.gz"
            self.assertEqual(network.read_bytes(), copied.read_bytes())
            with (output / "road_storage_capacity_v2.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = {row["link_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual("3", rows["d1"]["continuity_lane_floor_x_pcu"])
            self.assertEqual(3.0, float(rows["d1"]["storage_capacity_qsim_pcu"]))
            self.assertEqual("2", rows["d2"]["continuity_lane_floor_x_pcu"])
            self.assertEqual(2.0, float(rows["d2"]["storage_capacity_qsim_pcu"]))
            with (output / "road_supply_parameters_v2.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                registry = {row["link_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual("false", registry["untouched"]["storage_capacity_override"])
            self.assertEqual("7", registry["untouched"]["physical_length_m"])
            self.assertTrue(all(row["flow_capacity_override"] == "false" for row in registry.values()))
            summary = json.loads((output / "road_supply_candidate2_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["network_qa"]["byte_identical"])
            self.assertEqual(2, summary["registry"]["storage_override_links"])

    def test_all_road_scope_sets_lane_floor_on_every_physical_road(self) -> None:
        helper = RoadContinuityCandidateTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network, hotspots, neighbors = helper.prepare(root)
            output = root / "candidate3"
            subprocess.run([
                sys.executable, str(SCRIPT),
                "--input-network", str(network),
                "--hotspot-links", str(hotspots),
                "--hotspot-neighbors", str(neighbors),
                "--output-dir", str(output),
                "--storage-scope", "all-roads",
                "--expected-candidate-relationships", "3",
                "--expected-unique-links", "2",
                "--expected-road-links", "6",
            ], check=True, capture_output=True, text=True)
            copied = output / "network_tpdm3_physical_all_road_explicit_storage_v3.xml.gz"
            self.assertEqual(network.read_bytes(), copied.read_bytes())
            with (output / "road_supply_parameters_v3.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                registry = {row["link_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(6, len(registry))
            self.assertTrue(all(
                row["storage_capacity_override"] == "true"
                for row in registry.values()
            ))
            self.assertEqual("1", registry["untouched"]["storage_lane_floor_x_pcu"])
            self.assertEqual("false", registry["untouched"]["continuity_candidate"])
            self.assertEqual("3", registry["d1"]["storage_lane_floor_x_pcu"])
            self.assertEqual("true", registry["d1"]["continuity_candidate"])
            summary = json.loads(
                (output / "road_supply_candidate3_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual("all-roads", summary["selection"]["storage_scope"])
            self.assertEqual(2, summary["selection"]["continuity_target_links"])
            self.assertEqual(1, summary["selection"]["duplicate_target_relationships"])
            self.assertEqual(6, summary["registry"]["storage_override_links"])


if __name__ == "__main__":
    unittest.main()
