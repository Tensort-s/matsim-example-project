from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from lxml import etree as ET

import merge_hong_kong_no_ride_selective_routes as selective_merge
import prepare_hong_kong_no_ride_reallocation as no_ride


class NoRideReallocationTest(unittest.TestCase):
    def test_selective_merge_targets_both_members_of_each_student_pair(self) -> None:
        rows = []
        for index in range(956):
            rows.append(
                {
                    "displaced_person_id": f"bad_{index:04d}",
                    "donor_person_id": f"donor_{index:04d}",
                }
            )
        with tempfile.TemporaryDirectory() as directory:
            pairs = Path(directory) / "pairs.csv"
            pd.DataFrame(rows).to_csv(pairs, index=False, encoding="utf-8")
            targets = selective_merge.target_lookup(pairs)

        self.assertEqual(1_912, len(targets))
        self.assertEqual(3_824, sum(len(indices) for indices in targets.values()))
        self.assertTrue(all(indices == {0, 1} for indices in targets.values()))

    def test_student_pairing_uses_same_stratum_then_same_stage(self) -> None:
        displaced_rows = []
        donor_rows = []
        for index in range(956):
            displaced_rows.append(
                {
                    "person_id": f"bad_{index:04d}",
                    "student_stage": "special" if index == 955 else "primary",
                    "tcs_zone": 5 if index == 955 else 1,
                    "age": 10,
                    "sex": "M",
                    "home_x": float(index),
                    "home_y": 0.0,
                    "matsim_mode": "ride",
                    "mode_detail": "private_vehicle",
                    "household_private_vehicle_count": 0,
                }
            )
            donor_rows.append(
                {
                    "person_id": f"donor_{index:04d}",
                    "student_stage": "special" if index == 955 else "primary",
                    "tcs_zone": 6 if index == 955 else 1,
                    "age": 10,
                    "sex": "F",
                    "home_x": float(index),
                    "home_y": 1.0,
                    "matsim_mode": "pt" if index % 2 else "walk",
                    "mode_detail": "mtr" if index % 2 else "walk",
                    "household_private_vehicle_count": 1,
                }
            )

        pairs = no_ride.pair_student_swaps(
            pd.DataFrame(displaced_rows), pd.DataFrame(donor_rows)
        )

        self.assertEqual(956, len(pairs))
        self.assertEqual(956, pairs["donor_person_id"].nunique())
        self.assertEqual(
            {"same_stage_tcs": 955, "same_stage_nearest_home": 1},
            pairs["pairing_rule"].value_counts().to_dict(),
        )

    def test_adult_selection_is_exact_and_eligible(self) -> None:
        adults = pd.DataFrame(
            {
                "person_id": [f"adult_{index:04d}" for index in range(537)],
                "household_private_vehicle_count": [1] * 537,
                "tcs_zone": [index % 26 + 1 for index in range(537)],
                "sex": ["M" if index % 2 else "F" for index in range(537)],
                "age_band_census": ["25-34" if index % 3 else "35-44" for index in range(537)],
            }
        )

        selected = no_ride.select_adult_car_passengers(adults)

        self.assertEqual(122, len(selected))
        self.assertTrue(selected["household_private_vehicle_count"].gt(0).all())
        self.assertEqual(122, selected["person_id"].nunique())

    def test_config_eliminates_ride_and_adds_explicit_modes(self) -> None:
        source = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
  <module name="plans"><param name="inputPlansFile" value="old.xml.gz"/></module>
  <module name="controller"><param name="firstIteration" value="0"/><param name="lastIteration" value="50"/><param name="outputDirectory" value="old"/><param name="overwriteFiles" value="failIfDirectoryExists"/></module>
  <module name="transit"><param name="transitModes" value="pt"/></module>
  <module name="replanning">
    <parameterset type="strategysettings"><param name="strategyName" value="ChangeExpBeta"/><param name="weight" value="0.7"/></parameterset>
    <parameterset type="strategysettings"><param name="strategyName" value="ReRoute"/><param name="weight" value="0.1"/></parameterset>
    <parameterset type="strategysettings"><param name="strategyName" value="SubtourModeChoice"/><param name="weight" value="0.15"/></parameterset>
    <parameterset type="strategysettings"><param name="strategyName" value="TimeAllocationMutator"/><param name="weight" value="0.05"/></parameterset>
  </module>
  <module name="routing"><param name="networkModes" value="car"/></module>
  <module name="subtourModeChoice"><param name="modes" value="car,pt,walk,ride"/></module>
  <module name="scoring">
    <parameterset type="modeParams"><param name="mode" value="car"/><param name="monetaryDistanceRate" value="-0.0007"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="ride"/><param name="constant" value="-1.5"/></parameterset>
  </module>
</config>
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.xml"
            output = root / "route.xml"
            base.write_text(source, encoding="utf-8")

            audit = no_ride.transform_config(
                base,
                output,
                "/server/pre.xml.gz",
                "/server/output",
                route_only=True,
            )
            tree = ET.parse(str(output))

            self.assertEqual(0, audit["ride_value_occurrences"])
            self.assertEqual([], tree.xpath(".//param[@value='ride']"))
            self.assertEqual(
                ["car,pt,walk"],
                tree.xpath(
                    "/config/module[@name='subtourModeChoice']/param[@name='modes']/@value"
                ),
            )
            modes = set(
                tree.xpath(
                    "/config/module[@name='scoring']/parameterset[@type='modeParams']/param[@name='mode']/@value"
                )
            )
            self.assertEqual(
                {"car", "car_passenger", "school_bus", "taxi"}, modes
            )
            self.assertEqual(
                {"car_passenger", "pt", "school_bus", "walk"},
                set(
                    tree.xpath(
                        "/config/module[@name='routing']/parameterset[@type='teleportedModeParameters']/param[@name='mode']/@value"
                    )
                ),
            )
            self.assertEqual(
                ["0"],
                tree.xpath(
                    "/config/module[@name='scoring']/parameterset[param[@name='mode' and @value='car']]/param[@name='monetaryDistanceRate']/@value"
                ),
            )
            self.assertEqual(
                ["bus,gmb,train,light_rail,ferry"],
                tree.xpath(
                    "/config/module[@name='transit']/param[@name='transitModes']/@value"
                ),
            )
            self.assertEqual(
                ["1", "0", "0", "0"],
                tree.xpath(
                    "/config/module[@name='replanning']/parameterset/param[@name='weight']/@value"
                ),
            )


if __name__ == "__main__":
    unittest.main()
