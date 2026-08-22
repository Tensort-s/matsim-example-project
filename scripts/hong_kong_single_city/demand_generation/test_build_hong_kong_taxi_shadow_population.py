from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_hong_kong_taxi_shadow_population.py")
SPEC = importlib.util.spec_from_file_location("build_hong_kong_taxi_shadow_population", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


NETWORK = '''<?xml version="1.0" encoding="utf-8"?>
<network><nodes>
  <node id="a" x="0" y="0"/><node id="b" x="100" y="0"/>
  <node id="c" x="200" y="0"/><node id="d" x="300" y="0"/>
</nodes><links>
  <link id="ab" from="a" to="b" length="100" modes="car"/>
  <link id="bc" from="b" to="c" length="100" modes="car"/>
  <link id="cd" from="c" to="d" length="100" modes="car"/>
  <link id="pt" from="a" to="b" length="100" modes="pt"/>
</links></network>
'''

PLANS = '''<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">
<population><attributes><attribute name="coordinateReferenceSystem" class="java.lang.String">EPSG:32650</attribute></attributes>
<person id="p1"><attributes><attribute name="subpopulation" class="java.lang.String">resident</attribute></attributes>
<plan score="0" selected="yes"><activity type="home" link="ab" end_time="07:07:30"/>
<leg mode="taxi" dep_time="07:07:30" trav_time="00:10:00"><route type="generic" start_link="ab" end_link="cd" trav_time="00:10:00" distance="5000"/></leg>
<activity type="work" link="cd"/></plan></person>
<person id="p2"><plan selected="yes"><activity type="home" link="bc" end_time="08:00:00"/><leg mode="walk"/><activity type="shop" link="cd"/></plan></person>
</population>
'''


class TaxiShadowPopulationTest(unittest.TestCase):
    def test_builds_deterministic_tagged_shadow_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            network = root / "network.xml.gz"
            plans = root / "plans.xml.gz"
            submitted = root / "taxi_request_audit.csv.gz"
            with gzip.open(network, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(NETWORK)
            with gzip.open(plans, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(PLANS)
            with gzip.open(submitted, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write("request_id,person_ids,status\n")
                handle.write("taxi_0,p1,completed\n")

            outputs = []
            for name in ("one", "two"):
                output = root / f"{name}.xml.gz"
                audit = root / f"{name}.json"
                args = MODULE.parse_args([
                    "--plans", str(plans), "--network", str(network),
                    "--submitted-request-audit", str(submitted),
                    "--output-plans", str(output), "--output-audit", str(audit),
                    "--shadow-copies", "5", "--seed", "17",
                ])
                result = MODULE.run(args)
                self.assertEqual(result["counts"]["original_taxi_legs"], 1)
                self.assertEqual(result["counts"]["submitted_parent_taxi_legs"], 1)
                self.assertEqual(result["counts"]["shadow_persons"], 5)
                self.assertEqual(result["counts"]["output_persons"], 7)
                self.assertEqual(result["counts"]["output_taxi_legs"], 6)
                self.assertEqual(json.loads(audit.read_text(encoding="utf-8"))["status"], "validated")
                outputs.append(output)

            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with gzip.open(outputs[0], "rb") as handle:
                population = ET.parse(handle).getroot()
            persons = population.findall("person")
            self.assertEqual(len(persons), 7)
            self.assertEqual(persons[0].get("id"), "p1")
            self.assertEqual(persons[1].get("id"), "p2")
            shadows = persons[2:]
            self.assertTrue(all(person.get("id", "").startswith("hk_taxi_shadow_p1_0_") for person in shadows))
            for person in shadows:
                attrs = {
                    item.get("name"): item.text
                    for item in person.find("attributes").findall("attribute")
                }
                self.assertEqual(attrs[MODULE.SHADOW_ATTRIBUTE], "true")
                self.assertEqual(attrs["expansionWeight"], "0.0")
                plan = person.find("plan")
                origin, leg, destination = list(plan)
                self.assertEqual(origin.get("link"), "ab")
                self.assertEqual(destination.get("link"), "cd")
                self.assertEqual(origin.get("type"), "home")
                self.assertEqual(destination.get("type"), "home")
                departure = MODULE.parse_time(leg.get("dep_time"))
                self.assertGreaterEqual(departure, 7 * 3600)
                self.assertLess(departure, 7 * 3600 + 15 * 60)

    def test_rejects_unrouted_taxi_parent(self):
        broken = PLANS.replace(
            '<route type="generic" start_link="ab" end_link="cd" trav_time="00:10:00" distance="5000"/>',
            "",
        )
        with tempfile.TemporaryDirectory() as temp:
            plans = Path(temp) / "broken.xml.gz"
            with gzip.open(plans, "wt", encoding="utf-8") as handle:
                handle.write(broken)
            with self.assertRaisesRegex(ValueError, "lacks route"):
                MODULE.extract_taxi_legs(plans)


if __name__ == "__main__":
    unittest.main()
