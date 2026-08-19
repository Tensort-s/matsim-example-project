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
    "build_hong_kong_road_continuity_candidate.py"
)

NETWORK = """<?xml version="1.0" encoding="utf-8"?>
<network>
  <nodes>
    <node id="n1" x="0" y="0"/>
    <node id="n2" x="1" y="0"/>
    <node id="n3" x="2" y="0"/>
    <node id="n4" x="3" y="0"/>
  </nodes>
  <links capperiod="01:00:00">
    <link id="h1" from="n1" to="n2" length="100" freespeed="10" capacity="6100" permlanes="3" oneway="1" modes="car,bus"/>
    <link id="h2" from="n4" to="n2" length="80" freespeed="10" capacity="4050" permlanes="2" oneway="1" modes="car"/>
    <link id="d1" from="n2" to="n3" length="5" freespeed="10" capacity="1950" permlanes="1" oneway="1" modes="car,bus"/>
    <link id="h3" from="n3" to="n4" length="50" freespeed="10" capacity="4050" permlanes="2" oneway="1" modes="car"/>
    <link id="d2" from="n4" to="n1" length="8" freespeed="10" capacity="3000" permlanes="2" oneway="1" modes="car"/>
    <link id="untouched" from="n1" to="n4" length="7" freespeed="10" capacity="1000" permlanes="1" oneway="1" modes="car"/>
  </links>
</network>
"""


HOTSPOT_FIELDS = [
    "rank", "link_id", "street_ename", "lanes", "dominant_downstream_link",
    "dominant_downstream_share", "delay_vehicle_hours",
]
NEIGHBOR_FIELDS = [
    "hotspot_link", "relation", "link_id", "street_ename", "length_m",
    "lanes", "storage_proxy_vehicles",
]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class RoadContinuityCandidateTest(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path]:
        network = root / "network.xml.gz"
        with gzip.open(network, "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(NETWORK)
        hotspots = root / "hotspot_links.csv"
        write_csv(
            hotspots,
            HOTSPOT_FIELDS,
            [
                {"rank": "1", "link_id": "h1", "street_ename": "TEST ROAD", "lanes": "3", "dominant_downstream_link": "d1", "dominant_downstream_share": "0.95", "delay_vehicle_hours": "10"},
                {"rank": "2", "link_id": "h2", "street_ename": "TEST ROAD", "lanes": "2", "dominant_downstream_link": "d1", "dominant_downstream_share": "0.91", "delay_vehicle_hours": "8"},
                {"rank": "3", "link_id": "h3", "street_ename": "SECOND ROAD", "lanes": "2", "dominant_downstream_link": "d2", "dominant_downstream_share": "1", "delay_vehicle_hours": "6"},
                {"rank": "4", "link_id": "h1", "street_ename": "-99", "lanes": "3", "dominant_downstream_link": "untouched", "dominant_downstream_share": "1", "delay_vehicle_hours": "4"},
                {"rank": "5", "link_id": "h2", "street_ename": "TEST ROAD", "lanes": "2", "dominant_downstream_link": "untouched", "dominant_downstream_share": "0.89", "delay_vehicle_hours": "2"},
            ],
        )
        neighbors = root / "hotspot_neighbors.csv"
        write_csv(
            neighbors,
            NEIGHBOR_FIELDS,
            [
                {"hotspot_link": "h1", "relation": "downstream", "link_id": "d1", "street_ename": "TEST ROAD", "length_m": "5", "lanes": "1", "storage_proxy_vehicles": "0.066667"},
                {"hotspot_link": "h2", "relation": "downstream", "link_id": "d1", "street_ename": "TEST ROAD", "length_m": "5", "lanes": "1", "storage_proxy_vehicles": "0.066667"},
                {"hotspot_link": "h3", "relation": "downstream", "link_id": "d2", "street_ename": "SECOND ROAD", "length_m": "8", "lanes": "2", "storage_proxy_vehicles": "0.213333"},
                {"hotspot_link": "h1", "relation": "downstream", "link_id": "untouched", "street_ename": "-99", "length_m": "7", "lanes": "1", "storage_proxy_vehicles": "0.093333"},
                {"hotspot_link": "h2", "relation": "downstream", "link_id": "untouched", "street_ename": "TEST ROAD", "length_m": "7", "lanes": "1", "storage_proxy_vehicles": "0.093333"},
            ],
        )
        return network, hotspots, neighbors

    def command(
        self, network: Path, hotspots: Path, neighbors: Path, output: Path
    ) -> list[str]:
        return [
            sys.executable, str(SCRIPT),
            "--input-network", str(network),
            "--hotspot-links", str(hotspots),
            "--hotspot-neighbors", str(neighbors),
            "--output-dir", str(output),
            "--expected-candidate-relationships", "3",
            "--expected-unique-links", "2",
        ]

    def test_builds_only_selected_downstream_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network, hotspots, neighbors = self.prepare(root)
            output = root / "candidate"
            process = subprocess.run(
                self.command(network, hotspots, neighbors, output),
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn("candidate_generated_not_adopted", process.stdout)
            with gzip.open(
                output / "network_road_continuity_116.xml.gz", "rb"
            ) as handle:
                links = {
                    link.attrib["id"]: link.attrib
                    for link in ET.parse(handle).getroot().findall("./links/link")
                }
            self.assertEqual(3.0, float(links["d1"]["permlanes"]))
            self.assertEqual(25.0, float(links["d1"]["length"]))
            self.assertEqual(6100.0, float(links["d1"]["capacity"]))
            self.assertEqual(2.0, float(links["d2"]["permlanes"]))
            self.assertEqual(37.5, float(links["d2"]["length"]))
            self.assertEqual(4050.0, float(links["d2"]["capacity"]))
            self.assertEqual("7", links["untouched"]["length"])
            self.assertEqual("1000", links["untouched"]["capacity"])

            with (output / "continuity_candidate_relationships.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                relationships = list(csv.DictReader(handle))
            with (output / "continuity_link_changes.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                changes = list(csv.DictReader(handle))
            self.assertEqual(3, len(relationships))
            self.assertEqual({"d1", "d2"}, {row["link_id"] for row in changes})

            summary = json.loads(
                (output / "road_continuity_candidate_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(3, summary["selection"]["candidate_relationships"])
            self.assertEqual(2, summary["selection"]["unique_downstream_links"])
            self.assertEqual(1, summary["selection"]["duplicate_target_relationships"])
            self.assertTrue(all(summary["invariants"].values()))

    def test_fails_closed_if_candidate_count_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network, hotspots, neighbors = self.prepare(root)
            output = root / "candidate"
            command = self.command(network, hotspots, neighbors, output)
            command[command.index("3")] = "4"
            process = subprocess.run(
                command, check=False, text=True, capture_output=True
            )
            self.assertNotEqual(0, process.returncode)
            self.assertIn("expected 4, got 3", process.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
