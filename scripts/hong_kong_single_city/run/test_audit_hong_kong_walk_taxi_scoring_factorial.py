import unittest

from audit_hong_kong_walk_taxi_scoring_factorial import (
    factorial_effects,
    parse_arms,
    parse_iterations,
    percentile,
)


class AuditHongKongWalkTaxiScoringFactorialTest(unittest.TestCase):
    def test_strict_arm_and_iteration_parsing(self):
        self.assertEqual([0, 1, 2], parse_iterations("0-2"))
        self.assertEqual([0, 2, 4], parse_iterations("0,2,4"))
        arms = parse_arms(["a0=x0", "a1=x1", "a2=x2", "a3=x3"])
        self.assertEqual({"a0", "a1", "a2", "a3"}, set(arms))
        with self.assertRaises(ValueError):
            parse_arms(["a0=x0", "a1=x1", "a2=x2"])

    def test_percentile_interpolates(self):
        self.assertEqual(2.5, percentile([1, 2, 3, 4], 0.5))
        self.assertIsNone(percentile([], 0.5))

    def test_factorial_effects(self):
        def metrics(value):
            return {
                "overall_completion_rate": value,
                "average_executed_score": value,
                "by_planned_mode": {
                    "taxi": {"share": value, "completion_rate": value,
                             "mean_completed_minutes": value},
                    "walk": {"share": value, "completion_rate": value,
                             "mean_completed_minutes": value},
                },
                "taxi_requests": {"wait_mean_s": value},
            }

        result = factorial_effects({
            "a0": metrics(1.0), "a1": metrics(3.0),
            "a2": metrics(5.0), "a3": metrics(11.0),
        })
        effect = result["taxi_share"]
        self.assertEqual(4.0, effect["taxi_formula_main_effect"])
        self.assertEqual(6.0, effect["walk_formula_main_effect"])
        self.assertEqual(4.0, effect["interaction"])


if __name__ == "__main__":
    unittest.main()
