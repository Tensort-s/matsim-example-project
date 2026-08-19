from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name(
    "build_hong_kong_connector_chain_supply_candidate.py"
)

NETWORK = """<?xml version="1.0" encoding="utf-8"?>
<network>
  <nodes>
    <node id="n0" x="0" y="0"/>
    <node id="n1" x="100" y="0"/>
    <node id="n2" x="105" y="0"/>
    <node id="n3" x="110" y="0"/>
    <node id="n4" x="210" y="0"/>
  </nodes>
  <links capperiod="01:00:00">
    <link id="road_1_0_f" from="n0" to="n1" length="100" freespeed="10" capacity="6100" permlanes="3" oneway="1" modes="car,bus"/>
    <link id="road_2_0_f" from="n1" to="n2" length="5" freespeed="10" capacity="1950" permlanes="1" oneway="1" modes="car,bus"/>
    <link id="road_3_0_f" from="n2" to="n3" length="5" freespeed="10" capacity="1950" permlanes="1" oneway="1" modes="car,bus"/>
    <link id="road_4_0_f" from="n3" to="n4" length="100" freespeed="10" capacity="6100" permlanes="3" oneway="1" modes="car,bus"/>
  </links>
</network>
"""


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ConnectorChainSupplyCandidateTest(unittest.TestCase):
    def prepare(self, root: Path, ambiguous: bool = False) -> list[str]:
        network = root / "network.xml.gz"
        with gzip.open(network, "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(NETWORK)
        network_sha = hashlib.sha256(network.read_bytes()).hexdigest()

        registry = root / "road_supply_parameters_v3.csv"
        registry_fields = [
            "link_id", "physical_length_m", "physical_lanes", "freespeed_m_s",
            "flow_capacity_vph", "flow_capacity_source", "flow_capacity_override",
            "storage_capacity_qsim_pcu", "storage_capacity_source",
            "storage_capacity_override", "continuity_candidate",
            "storage_lane_floor_x_pcu", "continuity_lane_floor_x_pcu",
            "continuity_relationship_ids", "parameter_version",
            "source_network_sha256",
        ]
        network_values = {
            "road_1_0_f": (100, 3, 6100), "road_2_0_f": (5, 1, 1950),
            "road_3_0_f": (5, 1, 1950), "road_4_0_f": (100, 3, 6100),
        }
        registry_rows = []
        for link_id, (length, lanes, capacity) in network_values.items():
            continuity = link_id == "road_2_0_f"
            registry_rows.append({
                "link_id": link_id, "physical_length_m": str(length),
                "physical_lanes": str(lanes), "freespeed_m_s": "10",
                "flow_capacity_vph": str(capacity),
                "flow_capacity_source": "tpdm3", "flow_capacity_override": "false",
                "storage_capacity_qsim_pcu": str(max(lanes, 3 if continuity else lanes)),
                "storage_capacity_source": "all_road_x", "storage_capacity_override": "true",
                "continuity_candidate": str(continuity).lower(),
                "storage_lane_floor_x_pcu": str(3 if continuity else lanes),
                "continuity_lane_floor_x_pcu": "3" if continuity else "",
                "continuity_relationship_ids": "road_1_0_f->road_2_0_f" if continuity else "",
                "parameter_version": "v3", "source_network_sha256": network_sha,
            })
        write_csv(registry, registry_fields, registry_rows)

        previous = root / "previous.csv"
        previous_fields = [
            "upstream_link", "downstream_link", "street_ename", "upstream_lanes",
            "downstream_lanes", "hotspot_delay_vehicle_hours",
        ]
        write_csv(previous, previous_fields, [{
            "upstream_link": "road_1_0_f", "downstream_link": "road_2_0_f",
            "street_ename": "TEST ROAD", "upstream_lanes": "3",
            "downstream_lanes": "1", "hotspot_delay_vehicle_hours": "10",
        }])

        blocked = root / "blocked.csv"
        blocked_fields = [
            "link_id", "street_ename", "dominant_downstream_link",
            "dominant_downstream_share", "blocked_inflow_seconds",
            "delay_vehicle_hours", "dominant_downstream_lane_drop",
            "dominant_downstream_length_lt_10m", "representation_review_candidate",
            "review_category",
        ]
        blocked_rows = [{
            "link_id": "road_1_0_f", "street_ename": "TEST ROAD",
            "dominant_downstream_link": "road_2_0_f", "dominant_downstream_share": "0.99",
            "blocked_inflow_seconds": "25000", "delay_vehicle_hours": "10",
            "dominant_downstream_lane_drop": "true",
            "dominant_downstream_length_lt_10m": "true",
            "representation_review_candidate": "true", "review_category": "priority_representation",
        }]
        if not ambiguous:
            blocked_rows.extend([
                {
                    "link_id": "road_2_0_f", "street_ename": "TEST ROAD",
                    "dominant_downstream_link": "road_3_0_f", "dominant_downstream_share": "0.99",
                    "blocked_inflow_seconds": "25000", "delay_vehicle_hours": "9",
                    "dominant_downstream_lane_drop": "false",
                    "dominant_downstream_length_lt_10m": "true",
                    "representation_review_candidate": "false", "review_category": "",
                },
                {
                    "link_id": "road_3_0_f", "street_ename": "TEST ROAD",
                    "dominant_downstream_link": "road_4_0_f", "dominant_downstream_share": "0.99",
                    "blocked_inflow_seconds": "25000", "delay_vehicle_hours": "8",
                    "dominant_downstream_lane_drop": "false",
                    "dominant_downstream_length_lt_10m": "false",
                    "representation_review_candidate": "false", "review_category": "",
                },
            ])
        write_csv(blocked, blocked_fields, blocked_rows)

        routes = root / "routes.csv"
        route_ids = range(1, 3) if ambiguous else range(1, 5)
        write_csv(routes, ["route_id", "direction", "street_ename"], [
            {"route_id": str(index), "direction": "f", "street_ename": "TEST ROAD"}
            for index in route_ids
        ])
        output = root / "candidate4"
        return [
            sys.executable, str(SCRIPT), "--input-network", str(network),
            "--candidate3-registry", str(registry), "--blocked-link-audit", str(blocked),
            "--previous-relationships", str(previous), "--route-directions", str(routes),
            "--output-dir", str(output),
        ]

    def test_full_chain_gets_flow_and_storage_without_changing_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root)
            original = (root / "network.xml.gz").read_bytes()
            subprocess.run(command, check=True, capture_output=True, text=True)
            output = root / "candidate4"
            self.assertEqual(
                original,
                (output / "network_tpdm3_physical_connector_chain_v4.xml.gz").read_bytes(),
            )
            with (output / "road_supply_parameters_v4.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                registry = {row["link_id"]: row for row in csv.DictReader(handle)}
            for link_id in ("road_2_0_f", "road_3_0_f"):
                self.assertEqual("6100.000000000000", registry[link_id]["flow_capacity_vph"])
                self.assertEqual("true", registry[link_id]["flow_capacity_override"])
                self.assertGreaterEqual(float(registry[link_id]["storage_capacity_qsim_pcu"]), 3.0)
            self.assertEqual("1950.000000000000", registry["road_2_0_f"]["physical_flow_capacity_vph"])
            self.assertEqual("false", registry["road_1_0_f"]["flow_capacity_override"])
            with (output / "connector_chain_relationships_v4.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                segments = list(csv.DictReader(handle))
            self.assertEqual(["road_2_0_f", "road_3_0_f"], [row["segment_link"] for row in segments])
            with (output / "previous_candidate_chain_completion_audit_v4.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                previous = list(csv.DictReader(handle))
            self.assertEqual("true", previous[0]["previous_chain_was_incomplete"])
            self.assertEqual("road_3_0_f", previous[0]["missing_chain_segments_now_added"])
            summary = json.loads(
                (output / "road_supply_candidate4_summary.json").read_text(encoding="utf-8")
            )
            self.assertTrue(summary["qa"]["physical_network_byte_identical"])
            self.assertEqual(2, summary["selection"]["flow_override_links"])

    def test_unresolved_chain_is_rejected_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root, ambiguous=True)
            subprocess.run(command, check=True, capture_output=True, text=True)
            output = root / "candidate4"
            with (output / "connector_chain_relationships_v4.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                self.assertEqual([], list(csv.DictReader(handle)))
            with (output / "road_flow_capacity_v4.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                self.assertEqual([], list(csv.DictReader(handle)))
            with (output / "connector_chain_rejected_seeds_v4.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rejected = list(csv.DictReader(handle))
            self.assertEqual(1, len(rejected))
            self.assertEqual("0", rejected[0]["selected_segments"])


if __name__ == "__main__":
    unittest.main()
