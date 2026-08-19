from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from audit_hong_kong_experienced_pt_timetable_smoke import (
    common_metrics_with_mode_changes,
    safe_ratio,
    taxi_summary,
)
from finalize_hong_kong_experienced_pt_timetable_acceptance import corrected_summary


class ExperiencedPtTimetableSmokeAuditTest(unittest.TestCase):
    def test_safe_ratio_handles_zero_baseline(self) -> None:
        self.assertEqual(0.0, safe_ratio(0, 0))
        self.assertIsNone(safe_ratio(1, 0))
        self.assertAlmostEqual(0.5, safe_ratio(1, 2))

    def test_common_metrics_preserve_mode_transitions(self) -> None:
        base = {
            "a": ("walk", 1200.0),
            "b": ("pt", 1800.0),
            "base-only": ("pt", 600.0),
        }
        candidate = {
            "a": ("pt", 900.0),
            "b": ("pt", 1500.0),
            "candidate-only": ("pt", 300.0),
        }
        result = common_metrics_with_mode_changes(base, candidate)
        self.assertEqual(2, result["common_completed_trips"])
        self.assertEqual(1, result["same_mode_common_trips"])
        self.assertEqual({"pt->pt": 1, "walk->pt": 1}, result["mode_transitions"])
        self.assertAlmostEqual(-5.0, result["candidate_minus_base_mean_minutes_common"])
        self.assertEqual(1, result["candidate_only_completed"])
        self.assertEqual(1, result["base_only_completed"])

    def test_taxi_summary_conserves_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            output = run / "output/ITERS/it.0"
            output.mkdir(parents=True)
            (output / "0.taxi_operating_summary.csv").write_text(
                "submitted,completed,waiting,onboard,rejected,wait_p50_s,"
                "wait_p90_s,wait_p95_s,wait_p99_s,empty_vkt_km,occupied_vkt_km\n"
                "10,6,1,2,1,30,60,90,120,20,80\n",
                encoding="utf-8",
            )
            result = taxi_summary(run)
            self.assertTrue(result["request_conserved"])
            self.assertAlmostEqual(0.2, result["empty_vkt_share"])

    def test_corrected_gate_treats_zero_reference_errors_as_pass(self) -> None:
        source = {
            "candidate_unfinished_states": {
                "pt_waiting_before_boarding": 10,
                "pt_unfinished_onboard_or_transfer": 4,
            },
            "candidate5b_unfinished_states": {
                "pt_waiting_before_boarding": 18,
                "pt_unfinished_onboard_or_transfer": 2,
            },
            "technical_gates": {"exit_code_zero": True, "timetable_reference_qa_passed": False},
            "performance_gates": {
                "completion_not_lower_than_candidate5b": True,
                "pt_unfinished_onboard_or_transfer_not_worse": False,
            },
            "ratios": {},
        }
        timetable = {
            "qa": {
                "duplicate_departure_ids": 0,
                "missing_vehicle_references": 0,
                "all_adjusted_stop_offsets_monotonic": True,
                "day2_departure_times_within_target": True,
            }
        }
        result = corrected_summary(source, timetable)
        self.assertEqual("pt_timing_gate_passed_not_adopted", result["status"])
        self.assertTrue(result["technical_gates"]["timetable_reference_qa_passed"])
        self.assertAlmostEqual(0.7, result["ratios"]["combined_unresolved_pt_states"])

    def test_corrected_summary_serializes_zero_baseline_ratio_as_null(self) -> None:
        source = {
            "candidate_unfinished_states": {
                "pt_waiting_before_boarding": 5,
                "pt_unfinished_onboard_or_transfer": 1,
            },
            "candidate5b_unfinished_states": {
                "pt_waiting_before_boarding": 10,
                "pt_unfinished_onboard_or_transfer": 0,
            },
            "technical_gates": {"exit_code_zero": True},
            "performance_gates": {"completion_not_lower_than_candidate5b": True},
            "ratios": {"pt_unfinished_onboard_or_transfer": float("inf")},
        }
        timetable = {
            "qa": {
                "duplicate_departure_ids": 0,
                "missing_vehicle_references": 0,
                "all_adjusted_stop_offsets_monotonic": True,
                "day2_departure_times_within_target": True,
            }
        }
        result = corrected_summary(source, timetable)
        self.assertIsNone(result["ratios"]["pt_unfinished_onboard_or_transfer"])
        self.assertAlmostEqual(0.6, result["ratios"]["combined_unresolved_pt_states"])


if __name__ == "__main__":
    unittest.main()
