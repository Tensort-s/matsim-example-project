import gzip
from pathlib import Path
import tempfile
import unittest

from audit_hong_kong_road_network_runtime import (
    Link,
    classify_vehicle,
    geometry_endpoints,
    read_links,
    strongly_connected_components,
)


class RoadRuntimeAuditTest(unittest.TestCase):

    def test_vehicle_classification_separates_road_pt(self) -> None:
        self.assertEqual("private_car", classify_vehicle("hk_vehicle_1", "hk_person_1"))
        self.assertEqual("bus", classify_vehicle("veh_dep_bus_1", "pt_veh_dep_bus_1"))
        self.assertEqual("gmb", classify_vehicle("veh_dep_gmb_1", "pt_veh_dep_gmb_1"))
        self.assertEqual(
            "school_bus",
            classify_vehicle("veh_school_bus_v6_1", "pt_veh_school_bus_v6_1"),
        )

    def test_geometry_endpoints(self) -> None:
        self.assertEqual(
            ((1.0, 2.0), (5.0, 6.0)),
            geometry_endpoints("LINESTRING( 1 2, 3 4, 5 6 )"),
        )

    def test_directed_scc(self) -> None:
        def link(link_id: str, start: str, end: str) -> Link:
            return Link(
                link_id,
                start,
                end,
                10.0,
                10.0,
                1000.0,
                1.0,
                frozenset({"car"}),
                None,
                None,
            )

        links = {
            "ab": link("ab", "a", "b"),
            "ba": link("ba", "b", "a"),
            "bc": link("bc", "b", "c"),
        }
        components, in_degree, out_degree = strongly_connected_components(links)
        self.assertEqual([2, 1], [len(component) for component in components])
        self.assertEqual({"a", "b"}, components[0])
        self.assertNotIn("c", out_degree)
        self.assertEqual(1, in_degree["c"])

    def test_read_matsim_network_xml_gz(self) -> None:
        network = b'''<?xml version="1.0" encoding="UTF-8"?>
<network><nodes><node id="a" x="1" y="2"/><node id="b" x="3" y="4"/></nodes>
<links><link id="ab" from="a" to="b" length="25" freespeed="10"
capacity="1800" permlanes="2" modes="car,bus"/></links></network>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.xml.gz"
            with gzip.open(path, "wb") as stream:
                stream.write(network)
            links = read_links(path)
        link = links["ab"]
        self.assertEqual((1.0, 2.0), link.from_xy)
        self.assertEqual((3.0, 4.0), link.to_xy)
        self.assertEqual(frozenset({"car", "bus"}), link.modes)
        self.assertEqual(2.5, link.freeflow_s)


if __name__ == "__main__":
    unittest.main()
