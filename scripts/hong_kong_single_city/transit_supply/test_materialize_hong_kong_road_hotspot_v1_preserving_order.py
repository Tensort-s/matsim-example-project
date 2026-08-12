import unittest
import re

from materialize_hong_kong_road_hotspot_v1_preserving_order import (
    network_lengths_and_repair,
    repair_plan_routes,
    repair_schedule,
)


class PreserveOrderMaterializerTest(unittest.TestCase):
    def test_network_changes_only_restricted_modes(self):
        source = (
            '<network><links>'
            '<link id="road_261323_0_f" length="10" modes="car,bus" >'
            '<link id="road_105124_0_f" length="12" modes="car" >'
            '<link id="road_261308_0_f" length="6" modes="car" >'
            '<link id="road_285290_0_f" length="3" modes="car" >'
            '<link id="road_283946_0_f" length="4" modes="car" >'
            + ''.join(f'<link id="filler_{i}" length="1" modes="car" >' for i in range(100_000))
            + '</links></network>'
        )
        lengths, repaired = network_lengths_and_repair(source)
        self.assertEqual(100_005, len(lengths))
        self.assertIn('id="road_261323_0_f" length="10" modes="walk"', repaired)
        self.assertIn('id="road_261308_0_f" length="6" modes="walk"', repaired)

    def test_plan_route_preserves_surrounding_order(self):
        source = (
            '<person id="before"/><person id="p"><activity link="road_261323_0_f"/>'
            '<route type="links" start_link="a" end_link="z" distance="99">'
            'a road_261308_0_f z</route></person><person id="after"/>'
            + ' link="road_261323_0_f"' * 3
        )
        lengths = {"a": 1, "road_285290_0_f": 3, "road_283946_0_f": 4, "z": 2}
        repaired, count = repair_plan_routes(source, lengths)
        self.assertEqual(1, count)
        self.assertLess(repaired.index('id="before"'), repaired.index('id="p"'))
        self.assertLess(repaired.index('id="p"'), repaired.index('id="after"'))
        self.assertIn('a road_285290_0_f road_283946_0_f z', repaired)
        self.assertIn('distance="10"', repaired)
        self.assertEqual(4, repaired.count('link="road_105124_0_f"'))

    def test_schedule_handles_multiline_and_inline_route_links(self):
        source = (
            '<stopFacility id="s1" linkRefId="road_261323_0_f"/>'
            '<stopFacility id="s2" linkRefId="road_261308_0_f"/>'
            '<link refId="road_261323_0_f"/>tail'
            '<route><link refId="road_261308_0_f"/></route>'
        )
        repaired, route_count, stop_count = repair_schedule(
            source, {"s1": "road_105124_0_f", "s2": "road_283946_0_f"}
        )
        self.assertEqual(2, route_count)
        self.assertEqual(2, stop_count)
        self.assertNotIn("road_261323_0_f", repaired)
        self.assertNotIn("road_261308_0_f", repaired)
        self.assertIn(
            '<link refId="road_285290_0_f"/><link refId="road_283946_0_f"/>',
            repaired,
        )

    def test_entity_id_order_is_unchanged(self):
        network = (
            '<node id="n2"/><node id="n1"/>'
            '<link id="road_261323_0_f" length="1" modes="car" >'
            '<link id="road_105124_0_f" length="1" modes="car" >'
            '<link id="road_261308_0_f" length="1" modes="car" >'
            '<link id="road_285290_0_f" length="1" modes="car" >'
            '<link id="road_283946_0_f" length="1" modes="car" >'
            + ''.join(f'<link id="filler_{i}" length="1" modes="car" >' for i in range(100_000))
        )
        _, repaired = network_lengths_and_repair(network)
        pattern = re.compile(r'<(?:node|link) id="([^"]+)"')
        self.assertEqual(pattern.findall(network), pattern.findall(repaired))


if __name__ == "__main__":
    unittest.main()
