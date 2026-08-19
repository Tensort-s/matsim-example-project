from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).with_name(
    "build_hong_kong_experienced_pt_timetable_candidate.py"
)
SPEC = importlib.util.spec_from_file_location("experienced_pt", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


SCHEDULE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">
<transitSchedule>
  <transitStops>
    <stopFacility id="s0" x="0" y="0" linkRefId="l0"/>
    <stopFacility id="s1" x="100" y="0" linkRefId="l1"/>
    <stopFacility id="s2" x="200" y="0" linkRefId="l2"/>
  </transitStops>
  <transitLine id="line-A">
    <transitRoute id="route-A">
      <transportMode>bus</transportMode>
      <routeProfile>
        <stop refId="s0" departureOffset="00:00:00" awaitDeparture="true"/>
        <stop refId="s1" arrivalOffset="00:10:00" departureOffset="00:10:30" awaitDeparture="true"/>
        <stop refId="s2" arrivalOffset="00:20:00" awaitDeparture="true"/>
      </routeProfile>
      <route><link refId="l0"/><link refId="l1"/><link refId="l2"/></route>
      <departures>
        <departure id="dep-0" departureTime="00:30:00" vehicleRefId="veh-0"/>
        <departure id="dep-1" departureTime="01:30:00" vehicleRefId="veh-1"/>
      </departures>
    </transitRoute>
  </transitLine>
</transitSchedule>
"""

VEHICLES = """<?xml version="1.0" encoding="UTF-8"?>
<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd">
  <vehicleType id="bus"><capacity><seats persons="40"/><standingRoom persons="20"/></capacity><length meter="12"/></vehicleType>
  <vehicle id="veh-0" type="bus"/>
  <vehicle id="veh-1" type="bus"/>
</vehicleDefinitions>
"""

EVENTS = """<?xml version="1.0" encoding="utf-8"?>
<events version="1.0">
<event time="1700" type="TransitDriverStarts" driverId="d0" vehicleId="veh-0" transitLineId="line-A" transitRouteId="route-A" departureId="dep-0"/>
<event time="1800" type="VehicleDepartsAtFacility" vehicle="veh-0" facility="s0" delay="300"/>
<event time="2500" type="VehicleDepartsAtFacility" vehicle="veh-0" facility="s1" delay="400"/>
<event time="3200" type="VehicleArrivesAtFacility" vehicle="veh-0" facility="s2" delay="500"/>
<event time="5300" type="TransitDriverStarts" driverId="d1" vehicleId="veh-1" transitLineId="line-A" transitRouteId="route-A" departureId="dep-1"/>
<event time="5400" type="VehicleDepartsAtFacility" vehicle="veh-1" facility="s0" delay="600"/>
<event time="6100" type="VehicleDepartsAtFacility" vehicle="veh-1" facility="s1" delay="700"/>
<event time="6800" type="VehicleArrivesAtFacility" vehicle="veh-1" facility="s2" delay="800"/>
</events>
"""


def write_gzip(path: Path, text: str) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class ExperiencedPtTimetableCandidateTest(unittest.TestCase):
    def test_clock_rounding_carries_without_second_60(self) -> None:
        self.assertEqual("14:48:00", MODULE.clock(14 * 3600 + 47 * 60 + 59.9996))
        self.assertEqual("24:00:00", MODULE.clock(86_399.9996))

    def run_builder(self, root: Path) -> Path:
        schedule = root / "schedule.xml.gz"
        vehicles = root / "vehicles.xml.gz"
        events = root / "events.xml.gz"
        output = root / "candidate"
        write_gzip(schedule, SCHEDULE)
        write_gzip(vehicles, VEHICLES)
        write_gzip(events, EVENTS)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input-schedule", str(schedule),
                "--input-vehicles", str(vehicles),
                "--experienced-events", str(events),
                "--output-dir", str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output

    def test_preserves_route_ids_and_adds_complete_day2_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_builder(Path(directory))
            with gzip.open(
                output / "transitSchedule_experienced_day2_v1.xml.gz", "rb"
            ) as handle:
                root = ET.parse(handle).getroot()
            route = root.find("./transitLine/transitRoute")
            self.assertIsNotNone(route)
            assert route is not None
            self.assertEqual("line-A", root.find("./transitLine").get("id"))
            self.assertEqual("route-A", route.get("id"))
            stops = route.findall("./routeProfile/stop")
            self.assertEqual(["s0", "s1", "s2"], [stop.get("refId") for stop in stops])
            arrivals = [
                MODULE.seconds(stop.get("arrivalOffset") or stop.get("departureOffset"))
                for stop in stops
            ]
            departures = [
                MODULE.seconds(stop.get("departureOffset") or stop.get("arrivalOffset"))
                for stop in stops
            ]
            self.assertEqual(arrivals, sorted(arrivals))
            self.assertEqual(departures, sorted(departures))
            departure_elements = route.findall("./departures/departure")
            departure_ids = {item.get("id") for item in departure_elements}
            self.assertTrue({"dep-0", "dep-1"}.issubset(departure_ids))
            day2 = [item for item in departure_elements if item.get("id", "").endswith("__day2")]
            self.assertEqual(2, len(day2))
            self.assertTrue(all(86400 <= MODULE.seconds(item.get("departureTime")) < 108000 for item in day2))

            with gzip.open(
                output / "transitVehicles_experienced_day2_v1.xml.gz", "rb"
            ) as handle:
                vehicle_root = ET.parse(handle).getroot()
            vehicle_ids = {
                element.get("id")
                for element in vehicle_root.iter()
                if local(element.tag) == "vehicle"
            }
            self.assertTrue({item.get("vehicleRefId") for item in departure_elements} <= vehicle_ids)

            summary = json.loads(
                (output / "experienced_pt_timetable_candidate_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(1, summary["counts"]["routes_with_experienced_observations"])
            self.assertEqual(2, summary["counts"]["day2_departures_added"])
            self.assertEqual(0, summary["qa"]["duplicate_departure_ids"])
            self.assertEqual(0, summary["qa"]["missing_vehicle_references"])

    def test_output_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.run_builder(root)
            schedule = root / "schedule.xml.gz"
            vehicles = root / "vehicles.xml.gz"
            events = root / "events.xml.gz"
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    "--input-schedule", str(schedule),
                    "--input-vehicles", str(vehicles),
                    "--experienced-events", str(events),
                    "--output-dir", str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("FileExistsError", result.stderr)


if __name__ == "__main__":
    unittest.main()
