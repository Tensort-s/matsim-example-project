import unittest

from build_hong_kong_traffic_signal_pilot_v2_diagram_inferred import (
    ACTIVE_MOVEMENTS,
    derive_group_window,
    rows_by_period_for_junction,
)


class GroupWindowTest(unittest.TestCase):

    def setUp(self) -> None:
        self.rows = [
            row
            for row in rows_by_period_for_junction(
                "test", "test junction", 130, (37, 47, 46), (33, 51, 46)
            )
            if row["period"] == "am"
        ]

    def test_single_stage_window(self) -> None:
        self.assertEqual((130, 43, 84), derive_group_window(self.rows, "B"))

    def test_contiguous_multi_stage_window(self) -> None:
        self.assertEqual((130, 43, 130), derive_group_window(self.rows, "B|C"))

    def test_rejects_non_chronological_stage_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "chronological"):
            derive_group_window(self.rows, "C|B")

    def test_rejects_unknown_stage(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown"):
            derive_group_window(self.rows, "D")


class ActiveMovementRegistryTest(unittest.TestCase):

    def test_first_release_contains_only_audited_non_uturn_bundles(self) -> None:
        self.assertEqual(4, len(ACTIVE_MOVEMENTS))
        self.assertEqual(
            {"A", "B", "C"},
            {row["green_stage_labels"] for row in ACTIVE_MOVEMENTS},
        )
        self.assertTrue(
            all(row["from_link_id"] != row["to_link_id"] for row in ACTIVE_MOVEMENTS)
        )
        self.assertEqual(
            3,
            len({row["signal_group_id"] for row in ACTIVE_MOVEMENTS}),
        )


if __name__ == "__main__":
    unittest.main()
