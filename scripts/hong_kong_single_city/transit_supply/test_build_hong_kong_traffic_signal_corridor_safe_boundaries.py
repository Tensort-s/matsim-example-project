import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name(
    "build_hong_kong_traffic_signal_corridor_safe_boundaries.py"
)
SPEC = importlib.util.spec_from_file_location("safe_boundaries", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SafeBoundaryTests(unittest.TestCase):

    def test_shifted_bounds_wrap_midnight(self):
        self.assertEqual((13, 913), MODULE.shifted_bounds(0, 13))
        self.assertEqual((85513, 13), MODULE.shifted_bounds(95, 13))

    def test_fixed_offset_boundary_is_shared_stage1_barrier(self):
        old_windows = [
            {"stage_index": "1", "green_onset_s": "0", "green_dropping_s": "38"},
            {"stage_index": "2", "green_onset_s": "44", "green_dropping_s": "54"},
        ]
        new_windows = [
            {"stage_index": "1", "green_onset_s": "0", "green_dropping_s": "39"},
            {"stage_index": "2", "green_onset_s": "45", "green_dropping_s": "54"},
        ]
        self.assertTrue(
            MODULE.barrier_is_safe(913, 60, 60, 13, old_windows, new_windows)
        )
        self.assertFalse(
            MODULE.barrier_is_safe(900, 60, 60, 13, old_windows, new_windows)
        )

    def test_shared_barrier_supports_cycle_change(self):
        old_windows = [
            {"stage_index": "1", "green_onset_s": "0", "green_dropping_s": "44"},
            {"stage_index": "2", "green_onset_s": "50", "green_dropping_s": "69"},
        ]
        new_windows = [
            {"stage_index": "1", "green_onset_s": "0", "green_dropping_s": "38"},
            {"stage_index": "2", "green_onset_s": "44", "green_dropping_s": "54"},
        ]
        self.assertTrue(
            MODULE.barrier_is_safe(1813, 75, 60, 13, old_windows, new_windows)
        )


if __name__ == "__main__":
    unittest.main()
