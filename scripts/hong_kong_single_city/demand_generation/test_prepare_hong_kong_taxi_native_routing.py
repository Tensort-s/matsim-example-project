from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from lxml import etree as ET

import prepare_hong_kong_taxi_native_routing as native


PLANS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">
<population>
  <person id="p1"><plan selected="yes">
    <activity type="home" x="0" y="0" link="a"/>
    <leg mode="pt"><attributes><attribute name="routingMode" class="java.lang.String">pt</attribute></attributes><route type="generic" distance="1" trav_time="00:00:01"/></leg>
    <activity type="work" x="10" y="20" link="b"/>
    <leg mode="taxi" dep_time="08:00:00" trav_time="00:01:00"><attributes>
      <attribute name="routingMode" class="java.lang.String">ride</attribute>
      <attribute name="hkTaxiFareBaselineHkd" class="java.lang.Double">24.0</attribute>
      <attribute name="hkTaxiType" class="java.lang.String">urban_taxi</attribute>
      <attribute name="hkTaxiFareScope" class="java.lang.String">distance_only_v1</attribute>
      <attribute name="hkTaxiFareModelVersion" class="java.lang.String">hong_kong_taxi_fare_model_v1</attribute>
      <attribute name="hkTaxiClassificationSource" class="java.lang.String">synthetic</attribute>
      <attribute name="hkTaxiMainTripIndex" class="java.lang.Integer">1</attribute>
    </attributes><route type="generic" start_link="b" end_link="c" distance="1000" trav_time="00:01:00"/></leg>
    <activity type="shop" x="30" y="40" link="c"/>
  </plan></person>
</population>
"""


class NativeTaxiConversionTest(unittest.TestCase):
    def test_conversion_preserves_taxi_count_and_od(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xml.gz"
            output = root / "output.xml.gz"
            with gzip.open(
                source, "wt", encoding="utf-8", newline="\n"
            ) as handle:
                handle.write(PLANS)

            transformed = native.transform_plans(source, output)
            audited = native.audit_plans(output)

            self.assertEqual(1, transformed["taxi_count"])
            self.assertEqual(1, audited["taxi_count"])
            self.assertEqual(
                transformed["taxi_od_fingerprint_sha256"],
                audited["taxi_od_fingerprint_sha256"],
            )
            self.assertEqual({"taxi": 1}, audited[
                "taxi_routing_mode_counts"
            ])
            self.assertEqual(1, audited["taxi_trip_attribute_sets"])
            self.assertEqual(1, audited["mode_counts"]["taxi"])
            tree = ET.parse(str(output), ET.XMLParser())
            taxi = tree.xpath("//leg[@mode='taxi']")[0]
            self.assertEqual(
                "taxi",
                taxi.xpath(
                    "./attributes/attribute[@name='routingMode']/text()"
                )[0],
            )
            origin = tree.xpath("//activity[@type='work']")[0]
            self.assertEqual(
                set(native.TAXI_ATTRIBUTES),
                set(origin.xpath("./attributes/attribute/@name")),
            )

    def test_config_only_versions_plans_path(self) -> None:
        source_text = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
  <module name="plans"><param name="inputPlansFile" value="old.xml.gz"/></module>
  <module name="qsim"><param name="mainMode" value="car"/></module>
  <module name="routing"><param name="networkModes" value="car"/></module>
</config>
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "base.xml"
            output = root / "native.xml"
            source.write_text(source_text, encoding="utf-8")

            audit = native.transform_config(
                source, output, "/server/native-taxi.xml.gz"
            )

            self.assertEqual(["car"], audit["qsim_main_modes"])
            self.assertEqual(["car"], audit["routing_network_modes"])
            self.assertEqual([], audit["forbidden_modules"])
            self.assertEqual(
                "/server/native-taxi.xml.gz",
                ET.parse(str(output)).xpath(
                    "/config/module[@name='plans']/"
                    "param[@name='inputPlansFile']/@value"
                )[0],
            )


if __name__ == "__main__":
    unittest.main()
