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

    def test_cycle_options_all_fit_exact_15_minute_windows(self):
        self.assertTrue(all(900 % cycle == 0 for cycle in MODULE.CYCLE_OPTIONS_SECONDS))

    def test_green_allocation_preserves_minimum_and_clearance(self):
        for cycle in MODULE.CYCLE_OPTIONS_SECONDS:
            greens = MODULE.allocate_green(cycle, [0.4, 0.2])
            self.assertGreaterEqual(min(greens), MODULE.MIN_GREEN_SECONDS)
            self.assertEqual(sum(greens) + 2 * MODULE.CONTROLLER_CLEARANCE_SECONDS, cycle)

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
