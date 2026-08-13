import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from launch_hong_kong_traffic_signal_pilot import (
    set_qsim_stuck_time,
    validate_all_expressed_binding,
    write_config,
)


class TrafficSignalConfigTest(unittest.TestCase):

    def test_adds_explicit_opt_in_signal_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.xml"
            config.write_text("<config><module name='qsim'/></config>\n", encoding="utf-8")
            release = root / "release"
            write_config(config, release, root / "run", "am")
            parsed = ET.parse(config).getroot()
            modules = [
                item for item in parsed.findall("./module")
                if item.get("name") == "signalsystems"
            ]
            self.assertEqual(1, len(modules))
            values = {
                item.get("name"): item.get("value")
                for item in modules[0].findall("./param")
            }
            self.assertEqual("true", values["useSignalsystems"])
            self.assertEqual("true", values["useAmbertimes"])
            self.assertEqual("true", values["useIntergreentimes"])
            self.assertEqual("EXCEPTION", values["actionOnIntergreenViolation"])
            self.assertEqual("NONE", values["intersectionLogic"])
            self.assertTrue(values["signalsystems"].endswith("signal_systems.xml"))
            qsim_values = {
                item.get("name"): item.get("value")
                for item in parsed.find("./module[@name='qsim']").findall("./param")
            }
            self.assertEqual("false", qsim_values["usingFastCapacityUpdate"])

    def test_rejects_duplicate_signal_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.xml"
            config.write_text(
                "<config><module name='qsim'/><module name='signalsystems'/></config>\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "already contains"):
                write_config(config, root / "release", root / "run", "pm")

    def test_tod_uses_explicit_tod_payload_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.xml"
            config.write_text("<config><module name='qsim'/></config>\n", encoding="utf-8")
            release = root / "release"
            write_config(config, release, root / "run", "tod")
            module = ET.parse(config).getroot().find("./module[@name='signalsystems']")
            values = {
                item.get("name"): item.get("value")
                for item in module.findall("./param")
            }
            self.assertIn("traffic_signals_tod", values["signalcontrol"])

    def test_all_expressed_payload_requires_unified_diagram_validation(self) -> None:
        pilot = {"active_junction_count": 1929}
        valid = {
            "status": "pass",
            "selection_scope": "all_expressed",
            "junction_count": 1929,
            "public_diagram_junction_count": 8,
            "diagram_special_treatment_count": 0,
            "production_adopted": False,
        }
        validate_all_expressed_binding(pilot, valid)
        invalid = dict(valid, diagram_special_treatment_count=1)
        with self.assertRaisesRegex(ValueError, "validation binding"):
            validate_all_expressed_binding(pilot, invalid)

    def test_sets_explicit_positive_qsim_stuck_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.xml"
            config.write_text(
                "<config><module name='qsim'><param name='stuckTime' "
                "value='600'/></module></config>\n",
                encoding="utf-8",
            )
            set_qsim_stuck_time(config, 3600)
            parameter = ET.parse(config).getroot().find(
                "./module[@name='qsim']/param[@name='stuckTime']"
            )
            self.assertEqual("3600", parameter.get("value"))
            with self.assertRaisesRegex(ValueError, "positive"):
                set_qsim_stuck_time(config, 0)


if __name__ == "__main__":
    unittest.main()
