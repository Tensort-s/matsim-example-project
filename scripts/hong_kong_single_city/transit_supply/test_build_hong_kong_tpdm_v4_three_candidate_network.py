from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).with_name(
    "build_hong_kong_tpdm_v4_three_candidate_network.py"
)


NETWORK = """<?xml version="1.0" encoding="utf-8"?>
<network>
  <nodes>
    <node id="n1" x="0" y="0"/>
    <node id="n2" x="1" y="0"/>
  </nodes>
  <links capperiod="01:00:00">
    <link id="road_car_1" from="n1" to="n2" length="1" freespeed="1" capacity="1200" permlanes="1" oneway="1" modes="car,bus"/>
    <link id="road_car_2" from="n1" to="n2" length="1" freespeed="1" capacity="5000" permlanes="2" oneway="1" modes="car"/>
    <link id="road_bus_1" from="n2" to="n1" length="1" freespeed="1" capacity="1800" permlanes="1" oneway="1" modes="bus,gmb,pt"/>
    <link id="road_car_3" from="n2" to="n1" length="1" freespeed="1" capacity="3000" permlanes="3" oneway="1" modes="car"/>
    <link id="rail" from="n1" to="n2" length="1" freespeed="1" capacity="999" permlanes="1" oneway="1" modes="train"/>
  </links>
</network>
"""


class TpdmV4ThreeCandidateNetworkTest(unittest.TestCase):
    def test_builds_maximum_for_car_and_transit_only_road_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "network.xml.gz"
            output = root / "candidate"
            with gzip.open(source, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(NETWORK)
            process = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    "--input-network", str(source),
                    "--output-dir", str(output),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn("candidate_generated_not_adopted", process.stdout)
            with gzip.open(
                output / "network_tpdm_v4_three_candidate.xml.gz", "rb"
            ) as handle:
                network = ET.parse(handle).getroot()
            capacities = {
                link.attrib["id"]: float(link.attrib["capacity"])
                for link in network.findall("./links/link")
            }
            self.assertEqual(1950.0, capacities["road_car_1"])
            self.assertEqual(5000.0, capacities["road_car_2"])
            self.assertEqual(1950.0, capacities["road_bus_1"])
            self.assertEqual(6100.0, capacities["road_car_3"])
            self.assertEqual(999.0, capacities["rail"])

            with (output / "capacity_link_audit.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = {row["link_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual("tpdm_v4", rows["road_car_1"]["controlling_candidate"])
            self.assertEqual(
                "existing_two_candidate",
                rows["road_car_2"]["controlling_candidate"],
            )
            self.assertEqual("False", rows["road_bus_1"]["car_allowed"])

            summary = json.loads(
                (output / "tpdm_v4_three_candidate_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(5, summary["structure_qa"]["total_links"])
            self.assertEqual(4, summary["structure_qa"]["physical_road_links"])
            self.assertEqual(3, summary["structure_qa"]["changed_links"])
            self.assertEqual(
                {"tpdm_v4": 3, "existing_two_candidate": 1},
                summary["capacity_change"]["controlling_candidate_counts"],
            )
            self.assertEqual(
                2,
                summary["capacity_change"]["by_directional_lanes"]["1"][
                    "tpdm_v4_controlling_links"
                ],
            )
            self.assertTrue(all(summary["invariants"].values()))

    def test_tpdm_formula_uses_width_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "network.xml.gz"
            output = root / "candidate"
            with gzip.open(source, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(NETWORK)
            subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    "--input-network", str(source),
                    "--output-dir", str(output),
                    "--lane-width-m", "3.5",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            summary = json.loads(
                (output / "tpdm_v4_three_candidate_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(3.5, summary["method"]["lane_width_m"])
            with gzip.open(
                output / "network_tpdm_v4_three_candidate.xml.gz", "rb"
            ) as handle:
                network = ET.parse(handle).getroot()
            capacities = {
                link.attrib["id"]: float(link.attrib["capacity"])
                for link in network.findall("./links/link")
            }
            self.assertEqual(2000.0, capacities["road_car_1"])
            self.assertEqual(6200.0, capacities["road_car_3"])


if __name__ == "__main__":
    unittest.main()
