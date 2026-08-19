from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from build_hong_kong_aggressive_road_supply_candidate import (
    build_incidence,
    severe_runtime_components,
)


SCRIPT = Path(__file__).with_name("build_hong_kong_aggressive_road_supply_candidate.py")

NETWORK = """<?xml version="1.0" encoding="utf-8"?>
<network>
  <nodes>
    <node id="n0" x="0" y="0"/><node id="n1" x="100" y="0"/>
    <node id="n2" x="105" y="0"/><node id="n3" x="110" y="0"/>
    <node id="n4" x="105" y="5"/><node id="n5" x="210" y="0"/>
    <node id="n6" x="205" y="5"/>
  </nodes>
  <links capperiod="01:00:00">
    <link id="u" from="n0" to="n1" length="100" freespeed="10" capacity="6100" permlanes="3" modes="car"/>
    <link id="a" from="n1" to="n2" length="5" freespeed="10" capacity="1950" permlanes="1" modes="car"/>
    <link id="b" from="n2" to="n3" length="5" freespeed="10" capacity="1950" permlanes="1" modes="car"/>
    <link id="branch" from="n2" to="n4" length="5" freespeed="10" capacity="1950" permlanes="1" modes="car"/>
    <link id="cycle" from="n4" to="n2" length="5" freespeed="10" capacity="1950" permlanes="1" modes="car"/>
    <link id="exit" from="n3" to="n5" length="100" freespeed="10" capacity="6100" permlanes="3" modes="car"/>
    <link id="exitb" from="n4" to="n6" length="100" freespeed="10" capacity="6100" permlanes="3" modes="car"/>
  </links>
</network>
"""


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class AggressiveRoadSupplyCandidateTest(unittest.TestCase):
    def test_stage_b_boundaries_do_not_merge_distinct_core_chains(self) -> None:
        links = {
            "s1": {"from": "n0", "to": "n1", "length": "100", "permlanes": "1"},
            "boundary": {"from": "n1", "to": "n2", "length": "100", "permlanes": "1"},
            "s2": {"from": "n2", "to": "n3", "length": "100", "permlanes": "1"},
        }
        incoming, outgoing = build_incidence(links)
        source = [
            {"link_id": link_id, "candidate5_component": "false",
             "candidate5_component_ids": "", "candidate5_corridor_lane_x": ""}
            for link_id in links
        ]
        args = SimpleNamespace(
            severe_max_component_depth=12,
            severe_component_radius_m=250.0,
            short_link_m=30.0,
        )
        components = severe_runtime_components(
            {"s1", "s2"}, source, links, incoming, outgoing, args
        )
        self.assertEqual(2, len(components))
        self.assertTrue(all("boundary" in item["links"] for item in components))
        self.assertFalse(any({"s1", "s2"} <= item["links"] for item in components))

    def prepare(self, root: Path) -> tuple[Path, Path, Path, Path]:
        network = root / "network.xml.gz"
        with gzip.open(network, "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(NETWORK)
        network_sha = hashlib.sha256(network.read_bytes()).hexdigest()
        values = {
            "u": (100, 3, 6100), "a": (5, 1, 1950), "b": (5, 1, 1950),
            "branch": (5, 1, 1950), "cycle": (5, 1, 1950),
            "exit": (100, 3, 6100), "exitb": (100, 3, 6100),
        }
        registry_rows = []
        for link_id, (length, lanes, capacity) in values.items():
            registry_rows.append({
                "link_id": link_id, "physical_length_m": str(length),
                "physical_lanes": str(lanes), "freespeed_m_s": "10",
                "physical_flow_capacity_vph": str(capacity),
                "flow_capacity_vph": str(capacity), "flow_capacity_source": "candidate4",
                "flow_capacity_override": "false",
                "storage_capacity_qsim_pcu": str(lanes),
                "storage_capacity_source": "all_road_x",
                "storage_capacity_override": "true",
                "continuity_candidate": "false",
                "storage_lane_floor_x_pcu": str(lanes),
                "continuity_lane_floor_x_pcu": "",
                "continuity_relationship_ids": "",
                "parameter_version": "v4", "source_network_sha256": network_sha,
            })
        registry = root / "road_supply_parameters_v4.csv"
        write_csv(registry, registry_rows)
        blocked = root / "blocked.csv"
        write_csv(blocked, [
            {"link_id": "u", "dominant_downstream_link": "a",
             "representation_review_candidate": "true"},
            {"link_id": "b", "dominant_downstream_link": "exit",
             "representation_review_candidate": "false"},
        ])
        runtime = root / "runtime.csv"
        write_csv(runtime, [
            {"link_id": link_id, "blocked_inflow_seconds": "22000" if link_id == "u" else "0"}
            for link_id in values
        ])
        return network, registry, blocked, runtime

    def command(
        self, stage: str, network: Path, baseline: Path, source: Path,
        blocked: Path, runtime: Path, output: Path,
    ) -> list[str]:
        return [
            sys.executable, str(SCRIPT), "--stage", stage,
            "--input-network", str(network), "--baseline-registry", str(baseline),
            "--source-registry", str(source), "--runtime-supply-audit", str(runtime),
            "--blocked-link-audit", str(blocked), "--output-dir", str(output),
            "--expected-road-links", "7", "--expected-blocked-links", "2",
            "--expected-representation-seeds", "1",
        ]

    def test_stage_a_expands_branches_and_cycles_without_changing_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network, registry, blocked, runtime = self.prepare(root)
            original = network.read_bytes()
            output = root / "candidate5a"
            subprocess.run(
                self.command("A", network, registry, registry, blocked, runtime, output),
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(original, (output / "network_tpdm3_physical_candidate5a.xml.gz").read_bytes())
            result = {row["link_id"]: row for row in read_rows(output / "road_supply_parameters_v5a.csv")}
            for link_id in ("a", "b", "branch", "cycle"):
                self.assertEqual("true", result[link_id]["candidate5_component"])
                self.assertGreaterEqual(float(result[link_id]["storage_floor_pcu"]), 12.0)
            self.assertGreaterEqual(float(result["u"]["storage_floor_pcu"]), 6.0)
            self.assertEqual("1", result["a"]["storage_lane_floor_x_pcu"])
            summary = json.loads((output / "road_supply_candidate5a_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["qa"]["physical_network_byte_identical"])
            self.assertEqual(4, summary["selection"]["representation_component_unique_links"])
            self.assertEqual("representation_review", summary["selection"]["component_basis"])

    def test_stage_b_escalates_severe_noncomponent_flow_and_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network, registry, blocked, runtime = self.prepare(root)
            stage_a = root / "candidate5a"
            subprocess.run(
                self.command("A", network, registry, registry, blocked, runtime, stage_a),
                check=True, capture_output=True, text=True,
            )
            source = stage_a / "road_supply_parameters_v5a.csv"
            stage_b = root / "candidate5b"
            subprocess.run(
                self.command("B", network, registry, source, blocked, runtime, stage_b),
                check=True, capture_output=True, text=True,
            )
            result = {row["link_id"]: row for row in read_rows(stage_b / "road_supply_parameters_v5b.csv")}
            self.assertGreaterEqual(float(result["u"]["flow_capacity_vph"]), 1.25 * 6100)
            qsim_flow = float(result["u"]["flow_capacity_vph"]) * 0.1 / 3600.0
            self.assertGreaterEqual(float(result["u"]["storage_floor_pcu"]), 30.0 * qsim_flow)
            for link_id in ("a", "b", "branch", "cycle", "exit", "exitb"):
                self.assertEqual("true", result[link_id]["candidate5_component"])
                self.assertGreaterEqual(
                    float(result[link_id]["flow_capacity_vph"]),
                    1.25 * float(result[link_id]["physical_flow_capacity_vph"]),
                )
            component_rows = read_rows(stage_b / "road_component_membership_v5b.csv")
            self.assertEqual(set(result), {row["link_id"] for row in component_rows})
            summary = json.loads(
                (stage_b / "road_supply_candidate5b_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, summary["selection"]["severe_runtime_links"])
            self.assertEqual(7, summary["selection"]["severe_component_unique_links"])
            self.assertEqual("severe_runtime_complete_chain", summary["selection"]["component_basis"])


if __name__ == "__main__":
    unittest.main()
