#!/usr/bin/env python3
"""Tests for the Hong Kong traffic-signal TPDM proxy Stage-1 builder."""

from __future__ import annotations

import unittest
from collections import defaultdict
import json
from build_hong_kong_traffic_signal_pilot_v1 import Link, parse_network, read_csv
from build_hong_kong_traffic_signal_tpdm_proxy_stage1 import (
    DEFAULT_NETWORK,
    DEFAULT_OUTPUT,
    DEFAULT_REGISTRY,
    TS_K006_V2_BOUNDARIES,
    build_topology,
    classify_turn,
    enumerate_paths,
    movement_matcher,
)


def link(link_id: str, from_node: str, to_node: str) -> Link:
    return Link(link_id, from_node, to_node, 10.0, 10.0, 1800.0, 1.0, frozenset({"car"}), None)


class Stage1UnitTest(unittest.TestCase):
    def test_parameterised_turn_classifier_preserves_ambiguity_bands(self) -> None:
        self.assertEqual(classify_turn(0.0), "ahead")
        self.assertEqual(classify_turn(30.0), "ahead")
        self.assertEqual(classify_turn(31.0), "ambiguous")
        self.assertEqual(classify_turn(45.0), "left")
        self.assertEqual(classify_turn(-45.0), "right")
        self.assertEqual(classify_turn(140.0), "ambiguous")
        self.assertEqual(classify_turn(-150.0), "u_turn")

    def test_physical_path_enumeration_keeps_distinct_internal_sequences(self) -> None:
        approach = link("approach", "outside_w", "n0")
        internal_a = link("internal_a", "n0", "n1")
        internal_b = link("internal_b", "n0", "n2")
        exit_a = link("exit_a", "n1", "outside_e")
        exit_b = link("exit_b", "n2", "outside_e")
        outgoing = defaultdict(list)
        for item in (internal_a, internal_b, exit_a, exit_b):
            outgoing[item.from_node].append(item)
        paths, truncated = enumerate_paths(
            approach, {"n0", "n1", "n2"}, outgoing, max_internal_links=4, max_paths=10
        )
        self.assertFalse(truncated)
        self.assertEqual(
            [(sequence, exit_link.link_id) for sequence, exit_link in paths],
            [(('internal_a',), 'exit_a'), (('internal_b',), 'exit_b')],
        )

    def test_excluded_u_turn_never_enters_demand_matcher(self) -> None:
        base = {
            "from_link_id": "from", "internal_link_sequence": "inside",
            "exit_link_id": "exit", "movement_id": "m",
        }
        matcher = movement_matcher([
            {**base, "legal_status": "excluded_no_positive_evidence"},
        ])
        self.assertNotIn("from", matcher)
        matcher = movement_matcher([
            {**base, "legal_status": "unresolved", "demand_match_status": "excluded_shared_physical_path_between_registry_groups"},
        ])
        self.assertNotIn("from", matcher)

    def test_ts_k006_against_local_network_when_inputs_available(self) -> None:
        registry_path = DEFAULT_REGISTRY / "hong_kong_signal_junctions.csv"
        candidate_path = DEFAULT_REGISTRY / "signal_controlled_link_candidates.csv"
        if not (registry_path.exists() and candidate_path.exists() and DEFAULT_NETWORK.exists()):
            self.skipTest("Ignored Hong Kong candidate inputs are not present in this worktree")
        registry = [row for row in read_csv(registry_path) if row["signal_junction_id"] == "TS_K006"]
        candidates = [row for row in read_csv(candidate_path) if row["signal_junction_id"] == "TS_K006"]
        _, nodes, links = parse_network(DEFAULT_NETWORK)
        _, _, _, _, _, regression = build_topology(
            registry, candidates, nodes, links, max_internal_links=12, max_paths=2048
        )
        self.assertEqual(regression["status"], "pass")
        self.assertEqual(
            {key: set(value) for key, value in regression["actual"].items()},
            {" -> ".join(key): value for key, value in TS_K006_V2_BOUNDARIES.items()},
        )

    def test_candidate_output_contains_no_stage2_controller_artifact(self) -> None:
        if not DEFAULT_OUTPUT.exists():
            self.skipTest("Ignored Stage-1 candidate output is not present")
        forbidden = {
            path.name for path in DEFAULT_OUTPUT.iterdir()
            if path.suffix.lower() in {".xml", ".gz"}
            or any(word in path.name.lower() for word in ("cycle", "green_split", "offset", "controller"))
        }
        self.assertEqual(forbidden, set())

    def test_candidate_output_contract_when_available(self) -> None:
        if not DEFAULT_OUTPUT.exists():
            self.skipTest("Ignored Stage-1 candidate output is not present")
        required = {
            "signal_movements.csv", "signal_approaches.csv",
            "movement_topology_exceptions.csv", "u_turn_candidates.csv",
            "junction_network_expression_audit.csv",
            "vehicle_class_demand_scaling.csv", "movement_demand_15min.csv",
            "approach_demand_15min.csv", "junction_demand_15min.csv",
            "approach_flow_anchor_audit.csv", "approach_saturation_flow.csv",
            "saturation_flow_assumption_audit.csv", "stage1_qa_summary.json",
            "stage1_coverage_by_confidence.csv", "stage1_metadata.json",
        }
        self.assertTrue(all((DEFAULT_OUTPUT / name).exists() for name in required))
        movements = read_csv(DEFAULT_OUTPUT / "signal_movements.csv")
        uturns = read_csv(DEFAULT_OUTPUT / "u_turn_candidates.csv")
        junctions = read_csv(DEFAULT_OUTPUT / "junction_network_expression_audit.csv")
        saturation = read_csv(DEFAULT_OUTPUT / "approach_saturation_flow.csv")
        self.assertEqual(len(junctions), 2054)
        self.assertTrue(movements)
        self.assertEqual(len(uturns), sum(row["movement_type"] == "u_turn" for row in movements))
        self.assertTrue(all(row["activation_status"] == "not_activated" for row in uturns))
        self.assertTrue(all(row["capacity_separation"] == "comparison_only_network_not_modified" for row in saturation))
        with (DEFAULT_OUTPUT / "stage1_qa_summary.json").open(encoding="utf-8") as stream:
            qa = json.load(stream)
        self.assertFalse(qa["stage_boundary"]["forbidden_outputs_created"])
        self.assertEqual(qa["ts_k006_v2_regression"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
