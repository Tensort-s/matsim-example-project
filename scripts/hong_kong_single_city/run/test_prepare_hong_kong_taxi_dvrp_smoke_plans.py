import gzip
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from prepare_hong_kong_taxi_dvrp_smoke_plans import stable_person_ids, write_subset


class SmokePlansTest(unittest.TestCase):
    def test_exact_stable_subset_keeps_taxi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plans.xml.gz"
            with gzip.open(source, "wt", encoding="utf-8") as handle:
                handle.write('<population>')
                for index in range(10):
                    mode = "taxi" if index % 2 == 0 else "walk"
                    handle.write(
                        f'<person id="p{index}"><plan selected="yes">'
                        f'<act type="home" link="a"/><leg mode="{mode}"/>'
                        '<act type="work" link="b"/></plan></person>'
                    )
                handle.write('</population>')
            ids = stable_person_ids(source, 8)
            output = root / "smoke.xml.gz"
            result = write_subset(source, output, ids, expected_persons=8)
            self.assertEqual(8, result["persons"])
            self.assertGreater(result["selected_taxi_legs"], 0)
            with gzip.open(output, "rb") as handle:
                self.assertEqual(8, len(ET.parse(handle).getroot().findall("person")))

    def test_all_persons_selected_only_removes_unselected_plans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plans.xml"
            source.write_text(
                '<population><person id="p1"><plan selected="no">'
                '<act type="home"/></plan><plan selected="yes">'
                '<act type="home"/><leg mode="taxi"/><act type="work"/>'
                '</plan></person></population>',
                encoding="utf-8",
            )
            output = root / "selected.xml.gz"
            result = write_subset(
                source, output, None, expected_persons=1, selected_only=True
            )
            self.assertTrue(result["selected_only"])
            self.assertTrue(result["all_persons"])
            with gzip.open(output, "rb") as handle:
                plans = ET.parse(handle).getroot().findall("./person/plan")
            self.assertEqual(1, len(plans))
            self.assertEqual("yes", plans[0].get("selected"))


if __name__ == "__main__":
    unittest.main()
