import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from launch_hong_kong_candidate11_open_taxi_walk_20qsim import derive_config


class Candidate11OpenTaxiWalkConfigTest(unittest.TestCase):

    def test_freezes_twenty_qsim_contract_and_adopted_stuck_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.xml"
            destination = root / "derived" / "config.xml"
            run = root / "run"
            template.write_text(
                """<config>
                <module name="global"/>
                <module name="qsim"><param name="stuckTime" value="600"/></module>
                <module name="controller"/>
                <module name="scoring"/>
                <module name="subtourModeChoice"/>
                </config>\n""",
                encoding="utf-8",
            )

            derive_config(template, destination, run)
            parsed = ET.parse(destination).getroot()

            def values(name: str) -> dict[str, str]:
                module = parsed.find(f"./module[@name='{name}']")
                self.assertIsNotNone(module)
                return {
                    item.get("name"): item.get("value")
                    for item in module.findall("./param")
                }

            self.assertEqual("16", values("global")["numberOfThreads"])
            self.assertEqual("16", values("qsim")["numberOfThreads"])
            self.assertEqual("3600", values("qsim")["stuckTime"])
            controller = values("controller")
            self.assertEqual("0", controller["firstIteration"])
            self.assertEqual("19", controller["lastIteration"])
            self.assertEqual("10", controller["writeEventsInterval"])
            self.assertEqual("10", controller["writePlansInterval"])
            self.assertEqual("true", values("scoring")["writeExperiencedPlans"])
            self.assertEqual("car,pt,walk,taxi", values("subtourModeChoice")["modes"])


if __name__ == "__main__":
    unittest.main()
