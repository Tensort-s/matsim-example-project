import unittest

from audit_hong_kong_private_car_uturn_structure import base_route_id, structural_class


class PrivateCarUturnStructureTest(unittest.TestCase):

    def test_structural_classes_do_not_claim_illegality(self) -> None:
        self.assertEqual(
            "forced_reverse_only_dead_end_or_missing_connector",
            structural_class(0),
        )
        self.assertEqual(
            "low_choice_terminal_or_access_context",
            structural_class(1),
        )
        self.assertIn("requires_turn_evidence", structural_class(2))

    def test_base_route_strips_only_direction_suffix(self) -> None:
        self.assertEqual("road_7381_0", base_route_id("road_7381_0_f"))
        self.assertEqual("road_7381_0", base_route_id("road_7381_0_r"))


if __name__ == "__main__":
    unittest.main()
