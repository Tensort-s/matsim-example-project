import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("coordinate_hong_kong_traffic_signal_corridors.py")
SPEC = importlib.util.spec_from_file_location("signal_corridors", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CorridorTests(unittest.TestCase):

    def test_retain_consecutive_runs_wraps_midnight(self):
        values = [False] * 96
        values[95] = True
        values[0] = True
        values[10] = True
        result = MODULE.retain_consecutive_runs(values)
        self.assertTrue(result[95])
        self.assertTrue(result[0])
        self.assertFalse(result[10])

    def test_identical_zero_offset_plans_are_transition_safe(self):
        windows = [
            {"signal_group_id": "a", "green_onset_s": "0", "green_dropping_s": "24"},
            {"signal_group_id": "b", "green_onset_s": "30", "green_dropping_s": "54"},
        ]
        self.assertTrue(MODULE.transition_compatible(windows, 60, 0, windows, 60, 0))

    def test_offset_search_preserves_all_zero_profile(self):
        windows = [[
            {"signal_group_id": "a", "green_onset_s": "0", "green_dropping_s": "24"},
            {"signal_group_id": "b", "green_onset_s": "30", "green_dropping_s": "54"},
        ] for _ in range(96)]
        self.assertEqual(MODULE.choose_safe_offsets([0] * 96, [60] * 96, windows), [0] * 96)

    def test_safe_constant_offset_avoids_plan_boundary_jump(self):
        windows = [[
            {"signal_group_id": "a", "green_onset_s": "0", "green_dropping_s": "24"},
            {"signal_group_id": "b", "green_onset_s": "30", "green_dropping_s": "54"},
        ] for _ in range(96)]
        result = MODULE.choose_safe_constant_offset(
            [10] * 96, [True] * 96, [60] * 96, windows
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 10)


if __name__ == "__main__":
    unittest.main()
