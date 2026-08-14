import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("build_hong_kong_traffic_signal_tod_proxy_top100.py")
SPEC = importlib.util.spec_from_file_location("tod_top100", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TodTop100Tests(unittest.TestCase):

    def test_bin_index_folds_next_day_to_controller_day(self):
        self.assertEqual(MODULE.bin_index("00:00-00:15"), 0)
        self.assertEqual(MODULE.bin_index("23:45-24:00"), 95)
        self.assertEqual(MODULE.bin_index("24:00-24:15"), 0)
        self.assertEqual(MODULE.bin_index("30:15-30:30"), 25)

    def test_axis_clustering_pairs_opposite_approaches(self):
        approaches = [
            {"approach_id": "north", "approach_bearing_deg": "5"},
            {"approach_id": "south", "approach_bearing_deg": "185"},
            {"approach_id": "east", "approach_bearing_deg": "95"},
            {"approach_id": "west", "approach_bearing_deg": "275"},
        ]
        clusters = MODULE.cluster_approach_axes(approaches)
        self.assertEqual([{row["approach_id"] for row in cluster} for cluster in clusters], [
            {"north", "south"}, {"east", "west"}
        ])

    def test_cross_system_control_prefers_registry_then_demand(self):
        selected = [
            {
                "signal_junction_id": "TS_K014", "stage1_confidence": "high",
                "peak_tpdm_pcu_per_hour": 4736, "daily_tpdm_pcu_count": 46128,
            },
            {
                "signal_junction_id": "TS_OSM_0178", "stage1_confidence": "medium",
                "peak_tpdm_pcu_per_hour": 160, "daily_tpdm_pcu_count": 420,
            },
            {
                "signal_junction_id": "TS_K732", "stage1_confidence": "high",
                "peak_tpdm_pcu_per_hour": 728, "daily_tpdm_pcu_count": 4894,
            },
            {
                "signal_junction_id": "TS_K776", "stage1_confidence": "high",
                "peak_tpdm_pcu_per_hour": 1442, "daily_tpdm_pcu_count": 11102,
            },
        ]
        movements = [
            {"movement_id": "a", "from_link_id": "road_a", "signal_junction_id": "TS_K014"},
            {"movement_id": "b", "from_link_id": "road_a", "signal_junction_id": "TS_OSM_0178"},
            {"movement_id": "c", "from_link_id": "road_b", "signal_junction_id": "TS_K732"},
            {"movement_id": "d", "from_link_id": "road_b", "signal_junction_id": "TS_K776"},
        ]
        filtered, audit = MODULE.resolve_cross_system_control_ownership(movements, selected)
        self.assertEqual({row["movement_id"] for row in filtered}, {"a", "d"})
        self.assertEqual(len(audit), 2)

    def test_priority_override_can_merge_overfragmented_axes(self):
        approaches = [
            {"approach_id": str(index), "approach_bearing_deg": str(value)}
            for index, value in enumerate((11, 42, 73, 101, 144))
        ]
        self.assertEqual(len(MODULE.cluster_approach_axes(approaches, 25)), 5)
        self.assertEqual(len(MODULE.cluster_approach_axes(approaches, 40)), 3)

    def test_cycle_options_all_fit_exact_15_minute_windows(self):
        self.assertTrue(all(900 % cycle == 0 for cycle in MODULE.CYCLE_OPTIONS_SECONDS))

    def test_green_allocation_preserves_minimum_and_clearance(self):
        for cycle in MODULE.CYCLE_OPTIONS_SECONDS:
            greens = MODULE.allocate_green(cycle, [0.4, 0.2])
            self.assertGreaterEqual(min(greens), MODULE.MIN_GREEN_SECONDS)
            self.assertEqual(sum(greens) + 2 * MODULE.CONTROLLER_CLEARANCE_SECONDS, cycle)

    def test_green_allocation_supports_unified_one_and_five_axis_rule(self):
        for ratios in ([0.0], [0.3], [0.2, 0.1, 0.1, 0.05, 0.05]):
            cycle, _, _ = MODULE.recommended_cycle(ratios)
            greens = MODULE.allocate_green(cycle, ratios)
            self.assertEqual(len(greens), len(ratios))
            self.assertGreaterEqual(min(greens), MODULE.MIN_GREEN_SECONDS)
            self.assertEqual(
                sum(greens) + len(ratios) * MODULE.CONTROLLER_CLEARANCE_SECONDS,
                cycle,
            )

    def test_diagram_membership_is_not_an_executable_movement_rule(self):
        ordinary = {"movement_type": "straight", "demand_match_status": "matched"}
        self.assertTrue(MODULE.executable_movement(ordinary))
        self.assertNotIn("signal_junction_id", ordinary)
        self.assertEqual(len(MODULE.PUBLIC_DIAGRAM_JUNCTIONS), 8)

    def test_cycle_smoothing_never_undersizes_and_limits_grade_change(self):
        recommended = [60, 60, 100, 60, 75]
        smoothed = MODULE.smooth_cycle_indices(recommended)
        grades = [MODULE.CYCLE_OPTIONS_SECONDS.index(value) for value in smoothed]
        self.assertTrue(all(value >= minimum for value, minimum in zip(smoothed, recommended)))
        self.assertTrue(all(abs(left - right) <= 1 for left, right in zip(grades, grades[1:])))

    def test_webster_proxy_caps_oversaturated_period(self):
        cycle, ratio, status = MODULE.recommended_cycle([0.8, 0.4])
        self.assertEqual(cycle, 100)
        self.assertAlmostEqual(ratio, 1.2)
        self.assertEqual(status, "oversaturated_proxy_cycle_capped")


if __name__ == "__main__":
    unittest.main()
