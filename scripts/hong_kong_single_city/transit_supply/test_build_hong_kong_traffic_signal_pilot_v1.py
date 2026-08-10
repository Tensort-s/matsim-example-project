import unittest

from build_hong_kong_traffic_signal_pilot_v1 import (
    AMBER_SECONDS,
    CONTROLLER_ONSET_GAP_SECONDS,
    MINIMUM_INTERGREEN_SECONDS,
    RED_AMBER_SECONDS,
    color_conflict_graph,
    saturation_flow,
)


class SaturationFlowTest(unittest.TestCase):

    def test_tpdm_lane_defaults(self) -> None:
        self.assertEqual(1940.0, saturation_flow(1.0))
        self.assertEqual(4020.0, saturation_flow(2.0))
        self.assertEqual(6100.0, saturation_flow(3.0))


class ConflictGraphTest(unittest.TestCase):

    def test_conflicting_movements_never_share_stage(self) -> None:
        movements = [
            {"signal_id": "a", "preferred_stage_index": 0},
            {"signal_id": "b", "preferred_stage_index": 0},
            {"signal_id": "c", "preferred_stage_index": 1},
        ]
        result = color_conflict_graph(movements, [("a", "b"), ("b", "c")], 2)
        self.assertNotEqual(result["a"], result["b"])
        self.assertNotEqual(result["b"], result["c"])

    def test_fails_when_observed_stage_count_is_unsafe(self) -> None:
        movements = [
            {"signal_id": signal_id, "preferred_stage_index": 0}
            for signal_id in ("a", "b", "c")
        ]
        with self.assertRaisesRegex(ValueError, "requires more than 2 stages"):
            color_conflict_graph(
                movements,
                [("a", "b"), ("a", "c"), ("b", "c")],
                2,
            )


class SignalTimingSemanticsTest(unittest.TestCase):

    def test_controller_gap_produces_required_event_intergreen(self) -> None:
        event_intergreen = (
            CONTROLLER_ONSET_GAP_SECONDS + RED_AMBER_SECONDS - AMBER_SECONDS
        )
        self.assertEqual(MINIMUM_INTERGREEN_SECONDS, event_intergreen)


if __name__ == "__main__":
    unittest.main()
