import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("audit_hong_kong_traffic_signal_run.py")
SPEC = importlib.util.spec_from_file_location("signal_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ActiveTodPlanTests(unittest.TestCase):

    def test_shifted_plan_zero_wraps_from_previous_day(self):
        plans = [(0, 13, 913, 60), (95, 85513, 13, 75)]
        self.assertEqual(95, MODULE.active_tod_plan(0, plans)[0])
        self.assertEqual(0, MODULE.active_tod_plan(13, plans)[0])
        self.assertEqual(95, MODULE.active_tod_plan(86400, plans)[0])

    def test_exact_boundary_selects_new_plan(self):
        plans = [(0, 13, 913, 60), (1, 913, 1813, 75)]
        self.assertEqual(0, MODULE.active_tod_plan(912.999, plans)[0])
        self.assertEqual(1, MODULE.active_tod_plan(913, plans)[0])


if __name__ == "__main__":
    unittest.main()
