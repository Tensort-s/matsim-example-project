import unittest

from audit_hong_kong_road_network_runtime import Link
from extract_hong_kong_initial_car_uturn_observations import exact_reverse


class InitialCarUturnObservationTest(unittest.TestCase):

    def test_exact_reverse_uses_nodes(self) -> None:
        def link(link_id: str, start: str, end: str) -> Link:
            return Link(
                link_id, start, end, 10.0, 10.0, 1000.0, 1.0,
                frozenset({"car"}), None, None,
            )

        self.assertTrue(exact_reverse(link("x", "a", "b"), link("y", "b", "a")))
        self.assertFalse(exact_reverse(link("x", "a", "b"), link("z", "b", "c")))


if __name__ == "__main__":
    unittest.main()
