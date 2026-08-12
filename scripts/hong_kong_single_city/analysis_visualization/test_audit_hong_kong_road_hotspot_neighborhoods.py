import unittest

from audit_hong_kong_road_hotspot_neighborhoods import NetworkLink, select_hotspots


class RoadHotspotNeighborhoodAuditTest(unittest.TestCase):

    def test_selects_minimum_rows_reaching_share(self) -> None:
        rows = [
            {"link_id": "a", "total_delay_s": "60"},
            {"link_id": "b", "total_delay_s": "30"},
            {"link_id": "c", "total_delay_s": "10"},
        ]
        selected, actual = select_hotspots(rows, 0.5)
        self.assertEqual(["a"], [row["link_id"] for row in selected])
        self.assertAlmostEqual(0.6, actual)

    def test_storage_proxy(self) -> None:
        link = NetworkLink("a", "x", "y", 75.0, 10.0, 1000.0, 2.0, frozenset({"car"}))
        self.assertAlmostEqual(2.0, link.storage_proxy(0.1, 7.5))

    def test_rejects_invalid_share(self) -> None:
        with self.assertRaises(ValueError):
            select_hotspots([], 0)


if __name__ == "__main__":
    unittest.main()
