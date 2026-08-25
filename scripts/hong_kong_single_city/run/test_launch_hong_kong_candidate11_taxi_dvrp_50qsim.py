import gzip
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from launch_hong_kong_candidate11_taxi_dvrp_50qsim import (
    ALLOWED_TAXI_PCU,
    HOUSEHOLD_SELECTION_ITERATIONS,
    RUN_NAME_PREFIX,
    RUN_PROFILES,
    audit_population,
    audit_road_supply_registry,
    build_command,
    count_fleet_vehicles,
    count_population_persons,
    derive_config,
    validate_run_name,
)


TEMPLATE = """<config>
  <module name="global"/>
  <module name="network"><param name="inputNetworkFile" value="network.xml.gz"/></module>
  <module name="plans"><param name="inputPlansFile" value="full.xml.gz"/></module>
  <module name="qsim">
    <param name="flowCapacityFactor" value="0.1"/>
    <param name="storageCapacityFactor" value="0.1"/>
    <param name="stuckTime" value="600"/>
    <param name="removeStuckVehicles" value="true"/>
  </module>
  <module name="routing">
    <parameterset type="teleportedModeParameters">
      <param name="mode" value="walk"/>
      <param name="teleportedModeSpeed" value="1.34"/>
      <param name="beelineDistanceFactor" value="1.3"/>
    </parameterset>
  </module>
  <module name="controller"/>
  <module name="scoring"/>
  <module name="replanning">
    <param name="fractionOfIterationsToDisableInnovation" value="0.8"/>
    <parameterset type="strategysettings">
      <param name="strategyName" value="ChangeExpBeta"/>
      <param name="weight" value="0.70"/>
      <param name="disableAfterIteration" value="40"/>
    </parameterset>
    <parameterset type="strategysettings">
      <param name="strategyName" value="ReRoute"/>
      <param name="weight" value="0.10"/>
      <param name="disableAfterIteration" value="40"/>
    </parameterset>
    <parameterset type="strategysettings">
      <param name="strategyName" value="SubtourModeChoice"/>
      <param name="weight" value="0.15"/>
    </parameterset>
    <parameterset type="strategysettings">
      <param name="strategyName" value="TimeAllocationMutator_ReRoute"/>
      <param name="weight" value="0.05"/>
      <param name="disableAfterIteration" value="40"/>
    </parameterset>
    <parameterset type="strategysettings">
      <param name="strategyName" value="KeepLastSelected"/>
      <param name="subpopulation" value="hk_household_student_protected"/>
      <param name="weight" value="1.0"/>
    </parameterset>
  </module>
  <module name="subtourModeChoice"/>
  <module name="transit">
    <param name="useTransit" value="true"/>
    <param name="transitScheduleFile" value="schedule.xml.gz"/>
    <param name="vehiclesFile" value="vehicles.xml.gz"/>
  </module>
  <module name="signalsystems"><param name="useSignalsystems" value="true"/></module>
</config>
"""


def values(root: ET.Element, name: str) -> dict[str, str]:
    item = root.find(f"./module[@name='{name}']")
    if item is None:
        raise AssertionError(f"module {name} is missing")
    return {param.get("name", ""): param.get("value", "") for param in item.findall("./param")}


class Candidate11TaxiDvrpLauncherTest(unittest.TestCase):

    def test_rejects_post_run_config_without_walk_speed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.xml"
            destination = root / "derived" / "config.xml"
            template.write_text(
                TEMPLATE.replace(
                    '<param name="mode" value="walk"/>',
                    '<param name="mode" value="non_network_walk"/>',
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "pre-run config"):
                derive_config(
                    template,
                    destination,
                    root / "run",
                    RUN_PROFILES["smoke-0p5"],
                    plans_input=root / "plans.xml.gz",
                )

    def derive(self, profile_name: str, *, plans: Path | None = None) -> ET.Element:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        template = root / "template.xml"
        destination = root / "derived" / "config.xml"
        template.write_text(TEMPLATE, encoding="utf-8")
        derive_config(
            template,
            destination,
            root / "run",
            RUN_PROFILES[profile_name],
            plans_input=plans,
        )
        return ET.parse(destination).getroot()

    def tearDown(self) -> None:
        temporary = getattr(self, "temporary", None)
        if temporary is not None:
            temporary.cleanup()

    def test_formal_profile_freezes_fifty_qsim_contract(self) -> None:
        root = self.derive("formal-50")
        self.assertEqual("16", values(root, "global")["numberOfThreads"])
        qsim = values(root, "qsim")
        self.assertEqual("16", qsim["numberOfThreads"])
        self.assertEqual("0.1", qsim["flowCapacityFactor"])
        self.assertEqual("0.1", qsim["storageCapacityFactor"])
        self.assertEqual("3600", qsim["stuckTime"])
        self.assertEqual("false", qsim["removeStuckVehicles"])
        self.assertEqual("onlyUseStarttime", qsim["simStarttimeInterpretation"])
        controller = values(root, "controller")
        self.assertEqual("0", controller["firstIteration"])
        self.assertEqual("49", controller["lastIteration"])
        self.assertEqual("failIfDirectoryExists", controller["overwriteFiles"])
        for name in (
            "createGraphsInterval", "legDurationsInterval", "legHistogramInterval",
            "writeTripsInterval", "writeEventsInterval", "writePlansInterval",
        ):
            self.assertEqual("10", controller[name])
        self.assertEqual("true", values(root, "scoring")["writeExperiencedPlans"])

        candidate5b = RUN_PROFILES["formal-50-candidate5b"]
        self.assertEqual((0, 49), (
            candidate5b.first_iteration, candidate5b.last_iteration,
        ))
        self.assertTrue(candidate5b.traffic_signals)
        self.assertTrue(candidate5b.requires_network_override)
        self.assertFalse(candidate5b.fixed_selected_plans)
        self.assertEqual(44_000, candidate5b.expected_initial_taxi_legs)

        replanning = root.find("./module[@name='replanning']")
        assert replanning is not None
        self.assertEqual(
            "0.70", values(root, "replanning")["fractionOfIterationsToDisableInnovation"]
        )
        settings = {
            values_: {p.get("name"): p.get("value") for p in block.findall("./param")}
            for block in replanning.findall("./parameterset")
            if (values_ := next(
                p.get("value") for p in block.findall("./param")
                if p.get("name") == "strategyName"
            ))
        }
        self.assertNotIn("disableAfterIteration", settings["ChangeExpBeta"])
        self.assertNotIn("disableAfterIteration", settings["KeepLastSelected"])
        self.assertEqual("34", settings["ReRoute"]["disableAfterIteration"])
        self.assertEqual("34", settings["SubtourModeChoice"]["disableAfterIteration"])

    def test_candidate5b_checkpoint_resume_contract(self) -> None:
        plans = Path("/mnt/DiskM/by/example/40.plans.xml.zst")
        root = self.derive("formal-50-candidate5b-resume40", plans=plans)
        controller = values(root, "controller")
        self.assertEqual("41", controller["firstIteration"])
        self.assertEqual("49", controller["lastIteration"])
        self.assertEqual(str(plans), values(root, "plans")["inputPlansFile"])
        profile = RUN_PROFILES["formal-50-candidate5b-resume40"]
        self.assertEqual(3_378, profile.restored_household_bindings)
        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-12.0,
            profile=profile, xms="16g", xmx="128g",
        )
        self.assertIn("--household-joint-restore-selected-bindings=3378", command)
        self.assertFalse(any(
            item.startswith("--household-joint-selection-iterations=")
            for item in command
        ))

    def test_score_factorial_screening_changes_only_ordinary_mode_choice(self) -> None:
        root = self.derive("score-factorial-10")
        self.assertEqual("9", values(root, "controller")["lastIteration"])
        self.assertEqual("1", values(root, "controller")["writeTripsInterval"])
        self.assertEqual("1", values(root, "controller")["writePlansInterval"])
        self.assertEqual(
            "0.4", values(root, "replanning")["fractionOfIterationsToDisableInnovation"]
        )
        replanning = root.find("./module[@name='replanning']")
        assert replanning is not None
        settings = [
            {p.get("name"): p.get("value") for p in block.findall("./param")}
            for block in replanning.findall("./parameterset")
        ]
        ordinary = [item for item in settings if item.get("subpopulation", "") == ""]
        self.assertEqual({"ChangeExpBeta", "SubtourModeChoice"}, {
            item["strategyName"] for item in ordinary
        })
        subtour = next(item for item in ordinary if item["strategyName"] == "SubtourModeChoice")
        self.assertEqual("5", subtour["disableAfterIteration"])
        self.assertEqual("0.2", subtour["weight"])
        protected = [
            item for item in settings
            if item.get("subpopulation") == "hk_household_student_protected"
        ]
        self.assertEqual(["KeepLastSelected"], [item["strategyName"] for item in protected])

    def test_walk_repair_profile_allows_walk_and_scheduled_joint_selection(self) -> None:
        plans = Path("/mnt/DiskM/by/example/walk_choice_set_plans.xml.gz")
        root = self.derive("score-calibration-walk-repair-22", plans=plans)
        self.assertEqual(str(plans), values(root, "plans")["inputPlansFile"])
        self.assertEqual("car,pt,walk,taxi", values(root, "subtourModeChoice")["modes"])
        replanning = root.find("./module[@name='replanning']")
        assert replanning is not None
        ordinary = [
            {p.get("name"): p.get("value") for p in block.findall("./param")}
            for block in replanning.findall("./parameterset")
            if not any(
                p.get("name") == "subpopulation" for p in block.findall("./param")
            )
        ]
        self.assertEqual({
            "ChangeExpBeta", "ReRoute", "SubtourModeChoice",
            "TimeAllocationMutator_ReRoute",
        }, {item["strategyName"] for item in ordinary})
        for item in ordinary:
            if item["strategyName"] != "ChangeExpBeta":
                self.assertEqual("9", item["disableAfterIteration"])
        profile = RUN_PROFILES["score-calibration-walk-repair-22"]
        self.assertTrue(profile.requires_plans_override)
        self.assertTrue(profile.walk_choice_set_prepared)
        self.assertFalse(profile.household_protection_only)
        self.assertEqual(44_000, profile.expected_initial_taxi_legs)
        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-6.0,
            profile=profile, xms="16g", xmx="128g", scoring_arm="d2",
        )
        self.assertIn("--household-joint-plan-with-ordinary-innovation", command)
        self.assertIn("--household-joint-selection-iterations=5,15", command)
        student_catalog = next(
            item for item in command
            if item.startswith("--student-school-mode-candidates=")
        )
        self.assertTrue(student_catalog.replace("\\", "/").endswith(
            "/runtime/input/school_bus_plan_candidates_5pct_v6"
        ))
        self.assertNotIn("--household-joint-protection-only", command)

    def test_gradev2_profile_emits_one_named_scoring_contract(self) -> None:
        plans = Path("/mnt/DiskM/by/example/prepared_plans.xml.gz")
        root = self.derive("score-gradev2-walk-repair-22", plans=plans)
        self.assertEqual("21", values(root, "controller")["lastIteration"])
        profile = RUN_PROFILES["score-gradev2-walk-repair-22"]
        self.assertTrue(profile.scoring_grade_required)
        self.assertFalse(profile.scoring_arm_required)
        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-6.0,
            profile=profile, xms="16g", xmx="128g",
            scoring_grade="GradeV2",
        )
        self.assertIn("--scoring-grade=GradeV2", command)
        self.assertIn("--household-joint-selection-iterations=5,15", command)
        self.assertFalse(any(
            item.startswith("--taxi-wait-utility-per-hour=") for item in command
        ))
        self.assertFalse(any(
            item.startswith("--taxi-adult-fare-utility-per-hkd=") for item in command
        ))
        self.assertFalse(any(
            item.startswith("--walk-scoring-profile=") for item in command
        ))

    def test_score_calibration_25_keeps_ten_innovation_iterations(self) -> None:
        root = self.derive("score-calibration-25")
        controller = values(root, "controller")
        self.assertEqual("0", controller["firstIteration"])
        self.assertEqual("24", controller["lastIteration"])
        self.assertEqual("1", controller["writeTripsInterval"])
        self.assertEqual("1", controller["writePlansInterval"])
        self.assertEqual(
            "0.4", values(root, "replanning")["fractionOfIterationsToDisableInnovation"]
        )
        replanning = root.find("./module[@name='replanning']")
        assert replanning is not None
        settings = [
            {p.get("name"): p.get("value") for p in block.findall("./param")}
            for block in replanning.findall("./parameterset")
        ]
        subtour = next(
            item for item in settings
            if item.get("subpopulation", "") == ""
            and item.get("strategyName") == "SubtourModeChoice"
        )
        self.assertEqual("9", subtour["disableAfterIteration"])

    def test_score_calibration_22_keeps_ten_innovation_iterations(self) -> None:
        root = self.derive("score-calibration-22")
        controller = values(root, "controller")
        self.assertEqual("0", controller["firstIteration"])
        self.assertEqual("21", controller["lastIteration"])
        self.assertEqual("1", controller["writeTripsInterval"])
        self.assertEqual("1", controller["writePlansInterval"])
        replanning = root.find("./module[@name='replanning']")
        assert replanning is not None
        settings = [
            {p.get("name"): p.get("value") for p in block.findall("./param")}
            for block in replanning.findall("./parameterset")
        ]
        subtour = next(
            item for item in settings
            if item.get("subpopulation", "") == ""
            and item.get("strategyName") == "SubtourModeChoice"
        )
        self.assertEqual("9", subtour["disableAfterIteration"])

    def test_score_factorial_arms_emit_exact_walk_and_taxi_parameters(self) -> None:
        profile = RUN_PROFILES["score-factorial-10"]
        common = dict(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, profile=profile, xms="16g", xmx="128g",
        )
        a0 = build_command(
            **common, taxi_wait_utility_per_hour=-12.0, scoring_arm="a0"
        )
        a3 = build_command(
            **common, taxi_wait_utility_per_hour=-18.0, scoring_arm="a3"
        )
        b1 = build_command(
            **common, taxi_wait_utility_per_hour=-18.0, scoring_arm="b1"
        )
        b2 = build_command(
            **common, taxi_wait_utility_per_hour=-18.0, scoring_arm="b2"
        )
        calibration_profile = RUN_PROFILES["score-calibration-25"]
        calibration_common = {**common, "profile": calibration_profile}
        c1 = build_command(
            **calibration_common, taxi_wait_utility_per_hour=-6.0, scoring_arm="c1"
        )
        c2 = build_command(
            **calibration_common, taxi_wait_utility_per_hour=-18.0, scoring_arm="c2"
        )
        c3 = build_command(
            **calibration_common, taxi_wait_utility_per_hour=-6.0, scoring_arm="c3"
        )
        d1 = build_command(
            **{**common, "profile": RUN_PROFILES["score-calibration-22"]},
            taxi_wait_utility_per_hour=-6.0, scoring_arm="d1",
        )
        d2 = build_command(
            **{**common, "profile": RUN_PROFILES["score-calibration-22"]},
            taxi_wait_utility_per_hour=-6.0, scoring_arm="d2",
        )
        self.assertNotIn("--walk-scoring-profile=calibration-v2", a0)
        self.assertNotIn("--taxi-adult-fare-utility-per-hkd=0.12", a0)
        self.assertIn("--walk-scoring-profile=calibration-v2", a3)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=0.12", a3)
        self.assertIn("--taxi-student-fare-utility-per-hkd=0.18", a3)
        self.assertIn("--taxi-wait-utility-per-hour=-18", a3)
        self.assertIn("--household-joint-protection-only", a3)
        self.assertFalse(any(
            item.startswith("--household-joint-selection-iterations=") for item in a3
        ))
        self.assertIn("--walk-scoring-profile=calibration-v2", b1)
        self.assertIn("--taxi-constant-per-trip=-9.6", b1)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=0.125", b1)
        self.assertIn("--taxi-student-fare-utility-per-hkd=0.1875", b1)
        self.assertIn("--walk-scoring-profile=calibration-v3", b2)
        self.assertNotIn("--taxi-constant-per-trip=-9.6", b2)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=0.12", b2)
        self.assertIn("--taxi-student-fare-utility-per-hkd=0.18", b2)
        self.assertIn("--walk-scoring-profile=calibration-v2", c1)
        self.assertIn("--taxi-constant-per-trip=-9.6", c1)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=1", c1)
        self.assertIn("--taxi-student-fare-utility-per-hkd=1", c1)
        self.assertIn("--taxi-wait-utility-per-hour=-6", c1)
        self.assertIn("--walk-scoring-profile=calibration-v4", c2)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=0.12", c2)
        self.assertIn("--taxi-wait-utility-per-hour=-18", c2)
        self.assertIn("--walk-scoring-profile=calibration-v4", c3)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=1", c3)
        self.assertIn("--taxi-student-fare-utility-per-hkd=1", c3)
        self.assertIn("--taxi-wait-utility-per-hour=-6", c3)
        self.assertIn("--walk-scoring-profile=calibration-v2", d1)
        self.assertIn("--taxi-constant-per-trip=-9.6", d1)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=0.6", d1)
        self.assertIn("--taxi-student-fare-utility-per-hkd=0.7", d1)
        self.assertIn("--taxi-wait-utility-per-hour=-6", d1)
        self.assertIn("--walk-scoring-profile=calibration-v4", d2)
        self.assertIn("--taxi-constant-per-trip=-9.6", d2)
        self.assertIn("--taxi-adult-fare-utility-per-hkd=0.5", d2)
        self.assertIn("--taxi-student-fare-utility-per-hkd=0.6", d2)
        self.assertIn("--taxi-wait-utility-per-hour=-6", d2)

    def test_smoke_and_gate_profiles_have_safe_fixed_bounds(self) -> None:
        plans = Path("/mnt/DiskM/by/example/plans_0p5.xml.gz")
        smoke = self.derive("smoke-0p5", plans=plans)
        self.assertEqual("0", values(smoke, "controller")["lastIteration"])
        self.assertEqual("0.01", values(smoke, "qsim")["flowCapacityFactor"])
        self.assertEqual(str(plans), values(smoke, "plans")["inputPlansFile"])
        self.temporary.cleanup()
        self.temporary = None
        gate = self.derive("gate-0-1")
        self.assertEqual("1", values(gate, "controller")["lastIteration"])
        self.assertEqual("0.1", values(gate, "qsim")["flowCapacityFactor"])
        self.assertEqual(
            "0.0", values(gate, "replanning")["fractionOfIterationsToDisableInnovation"]
        )
        replanning = gate.find("./module[@name='replanning']")
        assert replanning is not None
        fixed_settings = [
            {p.get("name"): p.get("value") for p in block.findall("./param")}
            for block in replanning.findall("./parameterset")
        ]
        self.assertEqual(2, len(fixed_settings))
        self.assertTrue(all(item["strategyName"] == "KeepLastSelected" for item in fixed_settings))
        self.assertTrue(all(item["weight"] == "1.0" for item in fixed_settings))

        tcs_profile = RUN_PROFILES["freeze44k-tcs579011-fullfleet-it0"]
        self.assertEqual(15_500, tcs_profile.expected_fleet_size)
        self.assertEqual(921_035, tcs_profile.expected_population_size)
        self.assertEqual(579_215, tcs_profile.expected_initial_taxi_legs)
        self.assertTrue(tcs_profile.taxi_operational_parent_triggered)
        tcs_command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-12.0,
            profile=tcs_profile, xms="16g", xmx="128g",
        )
        self.assertIn("--taxi-operational-parent-triggered", tcs_command)
        high_occupancy_profile = RUN_PROFILES["freeze44k-tcs536121-fullfleet-it0"]
        self.assertEqual(15_500, high_occupancy_profile.expected_fleet_size)
        self.assertEqual(878_145, high_occupancy_profile.expected_population_size)
        self.assertEqual(536_325, high_occupancy_profile.expected_initial_taxi_legs)
        self.assertTrue(high_occupancy_profile.taxi_operational_parent_triggered)
        physical_profile = RUN_PROFILES["gate-0-1"]
        proxy_profile = RUN_PROFILES["gate-0-1-proxy"]
        self.assertEqual(
            (
                physical_profile.first_iteration,
                physical_profile.last_iteration,
                physical_profile.capacity_factor,
                physical_profile.expected_population_size,
                physical_profile.requires_plans_override,
                physical_profile.fixed_selected_plans,
            ),
            (
                proxy_profile.first_iteration,
                proxy_profile.last_iteration,
                proxy_profile.capacity_factor,
                proxy_profile.expected_population_size,
                proxy_profile.requires_plans_override,
                proxy_profile.fixed_selected_plans,
            ),
        )

    def test_nosignal_run7_profile_is_one_frozen_qsim(self) -> None:
        network = Path("/mnt/DiskM/by/example/run7_network.xml.gz")
        root = self.derive("nosignal-run7-it0")
        self.assertEqual("0", values(root, "controller")["firstIteration"])
        self.assertEqual("0", values(root, "controller")["lastIteration"])
        self.assertEqual("0.1", values(root, "qsim")["flowCapacityFactor"])
        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        temp_root = Path(self.temporary.name)
        template = temp_root / "template.xml"
        destination = temp_root / "derived" / "config.xml"
        template.write_text(TEMPLATE, encoding="utf-8")
        derive_config(
            template, destination, temp_root / "run",
            RUN_PROFILES["nosignal-run7-it0"], network_input=network,
        )
        derived = ET.parse(destination).getroot()
        self.assertEqual(str(network), values(derived, "network")["inputNetworkFile"])
        self.assertEqual("false", values(derived, "signalsystems")["useSignalsystems"])

        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=1.0, taxi_wait_utility_per_hour=-12.0,
            profile=RUN_PROFILES["nosignal-run7-it0"], xms="16g", xmx="128g",
        )
        self.assertNotIn("--traffic-signals", command)

    def test_nosignal_original_profile_replans_before_one_qsim_and_allows_pcu_005(self) -> None:
        self.assertIn(0.05, ALLOWED_TAXI_PCU)
        profile = RUN_PROFILES["nosignal-run7-original-it0"]
        self.assertEqual((0, 0), (profile.first_iteration, profile.last_iteration))
        self.assertFalse(profile.fixed_selected_plans)
        self.assertFalse(profile.traffic_signals)
        self.assertTrue(profile.requires_network_override)
        self.assertEqual(44_000, profile.expected_initial_taxi_legs)

        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-12.0,
            profile=profile, xms="16g", xmx="96g",
        )
        self.assertIn("--taxi-dvrp-pcu=0.05", command)
        self.assertIn("--all-person-network-taxi-innovation", command)
        self.assertIn("--clear-pt-routes", command)
        self.assertNotIn("--traffic-signals", command)
        self.assertFalse(any(
            item.startswith("--household-joint-selection-iterations=")
            for item in command
        ))

    def test_candidate5b_signal_profile_changes_only_signal_runtime_contract(self) -> None:
        signal = RUN_PROFILES["signal-candidate5b-original-it0"]
        no_signal = RUN_PROFILES["nosignal-run7-original-it0"]
        comparable = (
            "first_iteration", "last_iteration", "capacity_factor",
            "expected_fleet_size", "expected_population_size", "taxi_execution",
            "fixed_selected_plans", "requires_network_override",
            "expected_initial_taxi_legs", "stuck_time_s", "remove_stuck_vehicles",
        )
        self.assertEqual(
            tuple(getattr(signal, name) for name in comparable),
            tuple(getattr(no_signal, name) for name in comparable),
        )
        self.assertTrue(signal.traffic_signals)
        self.assertFalse(no_signal.traffic_signals)

        self.temporary = tempfile.TemporaryDirectory()
        temp_root = Path(self.temporary.name)
        template = temp_root / "template.xml"
        destination = temp_root / "derived" / "config.xml"
        template.write_text(TEMPLATE, encoding="utf-8")
        derive_config(
            template, destination, temp_root / "run", signal,
            network_input=Path("/mnt/DiskM/by/example/candidate5b.xml.gz"),
        )
        root = ET.parse(destination).getroot()
        self.assertEqual("true", values(root, "signalsystems")["useSignalsystems"])
        self.assertEqual("false", values(root, "qsim")["usingFastCapacityUpdate"])
        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-12.0,
            profile=signal, xms="16g", xmx="96g",
        )
        self.assertIn("--traffic-signals", command)
        self.assertIn("--clear-pt-routes", command)

    def test_freeze44k_shadow6_profile_is_fixed_30pct_operational_layer(self) -> None:
        profile = RUN_PROFILES["freeze44k-shadow6-30pct-it0"]
        self.assertEqual((0, 0), (profile.first_iteration, profile.last_iteration))
        self.assertEqual(4_650, profile.expected_fleet_size)
        self.assertEqual(604_800, profile.expected_population_size)
        self.assertEqual(262_980, profile.expected_initial_taxi_legs)
        self.assertTrue(profile.fixed_selected_plans)
        self.assertTrue(profile.traffic_signals)
        self.assertTrue(profile.requires_network_override)
        self.assertAlmostEqual(0.30, profile.taxi_operational_sample_share)
        self.assertIn(1.0 / 6.0, ALLOWED_TAXI_PCU)

        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=1.0 / 6.0, taxi_wait_utility_per_hour=-12.0,
            profile=profile, xms="16g", xmx="128g",
            road_supply_registry=Path("/release/road_supply.csv"),
        )
        self.assertIn("--taxi-dvrp-pcu=0.16666666666666666", command)
        self.assertIn("--taxi-operational-sample-share=0.3", command)
        self.assertIn(f"--road-supply-registry={Path('/release/road_supply.csv')}", command)
        self.assertIn("--clear-pt-routes", command)
        self.assertNotIn("--all-person-network-taxi-innovation", command)

    def test_transit_schedule_and_vehicle_overrides_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.xml"
            destination = root / "derived" / "config.xml"
            template.write_text(TEMPLATE, encoding="utf-8")
            schedule = Path("/mnt/DiskM/by/example/transitSchedule_day2.xml.gz")
            vehicles = Path("/mnt/DiskM/by/example/transitVehicles_day2.xml.gz")
            derive_config(
                template,
                destination,
                root / "run",
                RUN_PROFILES["nosignal-run7-original-it0"],
                transit_schedule_input=schedule,
                transit_vehicles_input=vehicles,
            )
            derived = ET.parse(destination).getroot()
            self.assertEqual(str(schedule), values(derived, "transit")["transitScheduleFile"])
            self.assertEqual(str(vehicles), values(derived, "transit")["vehiclesFile"])

            with self.assertRaisesRegex(ValueError, "supplied together"):
                derive_config(
                    template,
                    root / "other" / "config.xml",
                    root / "run2",
                    RUN_PROFILES["nosignal-run7-original-it0"],
                    transit_schedule_input=schedule,
                )

    def test_explicit_storage_registry_is_an_opt_in_physical_taxi_flag(self) -> None:
        registry = Path("/release/input/road_supply_parameters_v2.csv")
        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.05, taxi_wait_utility_per_hour=-12.0,
            profile=RUN_PROFILES["nosignal-run7-original-it0"],
            xms="16g", xmx="96g", road_supply_registry=registry,
        )
        self.assertIn(f"--road-supply-registry={registry}", command)

    def test_road_supply_registry_audit_accepts_dynamic_override_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "road_supply_parameters_v3.csv"
            path.write_text(
                "link_id,storage_capacity_override,flow_capacity_override\n"
                "a,true,true\n"
                "b,true,false\n"
                "c,false,false\n",
                encoding="utf-8",
            )
            audit = audit_road_supply_registry(path)
            self.assertEqual(3, audit.road_links)
            self.assertEqual(2, audit.storage_overrides)
            self.assertEqual(1, audit.flow_overrides)

    def test_teleported_control_matches_run7_without_physical_taxi_flags(self) -> None:
        profile = RUN_PROFILES["nosignal-run7-teleported-control-it0"]
        self.assertEqual("teleported", profile.taxi_execution)
        self.assertEqual((0, 0), (profile.first_iteration, profile.last_iteration))
        self.assertFalse(profile.traffic_signals)
        self.assertTrue(profile.requires_network_override)
        self.assertEqual(44_000, profile.expected_initial_taxi_legs)

        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=None,
            taxi_pcu=1.0, taxi_wait_utility_per_hour=-12.0,
            profile=profile, xms="16g", xmx="96g",
        )
        self.assertIn("--clear-pt-routes", command)
        self.assertFalse(any(
            item.startswith("--household-joint-plan-candidates=") for item in command
        ))
        forbidden = (
            "--taxi-dvrp-fleet=", "--taxi-dvrp-pcu=",
            "--taxi-wait-utility-per-hour=",
            "--household-joint-selection-iterations=",
        )
        self.assertFalse(any(item.startswith(forbidden) for item in command))
        self.assertNotIn("--fixed-plans-network-taxi-proxy", command)
        self.assertNotIn("--all-person-network-taxi-innovation", command)
        self.assertNotIn("--household-joint-plan-with-ordinary-innovation", command)
        self.assertNotIn("--walk-overtime-scoring", command)
        self.assertNotIn("--traffic-signals", command)

    def test_old_stuck_control_changes_only_qsim_stuck_policy(self) -> None:
        current = RUN_PROFILES["nosignal-run7-teleported-control-it0"]
        historical = RUN_PROFILES["nosignal-run7-teleported-oldstuck-it0"]
        self.assertEqual(3600, current.stuck_time_s)
        self.assertFalse(current.remove_stuck_vehicles)
        self.assertEqual(600, historical.stuck_time_s)
        self.assertTrue(historical.remove_stuck_vehicles)
        comparable_fields = (
            "first_iteration", "last_iteration", "capacity_factor",
            "expected_fleet_size", "expected_population_size",
            "taxi_execution", "requires_plans_override",
            "fixed_selected_plans", "traffic_signals",
            "requires_network_override", "expected_initial_taxi_legs",
        )
        self.assertEqual(
            tuple(getattr(current, name) for name in comparable_fields),
            tuple(getattr(historical, name) for name in comparable_fields),
        )

    def test_command_uses_physical_fleet_and_explicit_scoring_contract(self) -> None:
        command = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=0.25, taxi_wait_utility_per_hour=-12.0,
            profile=RUN_PROFILES["formal-50"],
            xms="16g", xmx="128g",
        )
        self.assertIn(
            f"--taxi-dvrp-fleet={Path('/release/fleet.xml.gz')}", command
        )
        self.assertIn("--taxi-dvrp-pcu=0.25", command)
        self.assertIn("--taxi-wait-utility-per-hour=-12", command)
        self.assertIn("--clear-pt-routes", command)
        self.assertIn(
            f"--household-joint-selection-iterations={','.join(map(str, HOUSEHOLD_SELECTION_ITERATIONS))}",
            command,
        )
        self.assertIn("--all-person-network-taxi-innovation", command)

        fixed = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=Path("/release/fleet.xml.gz"),
            taxi_pcu=1.0, taxi_wait_utility_per_hour=-12.0,
            profile=RUN_PROFILES["gate-0-1"], xms="16g", xmx="128g",
        )
        self.assertNotIn("--clear-pt-routes", fixed)
        forbidden_prefixes = (
            "--household-joint-plan-candidates=",
            "--household-joint-selection-iterations=",
        )
        self.assertFalse(any(item.startswith(forbidden_prefixes) for item in fixed))
        self.assertTrue(any(
            item.startswith("--student-school-mode-candidates=") for item in fixed
        ))
        self.assertNotIn("--household-joint-plan-with-ordinary-innovation", fixed)
        self.assertNotIn("--all-person-network-taxi-innovation", fixed)

        proxy = build_command(
            java=Path("/runtime/java"), jar=Path("/release/app.jar"),
            config=Path("/run/config.xml"), cost_root=Path("/release/cost"),
            runtime=Path("/runtime"), fleet=None,
            taxi_pcu=1.0, taxi_wait_utility_per_hour=-12.0,
            profile=RUN_PROFILES["gate-0-1-proxy"], xms="16g", xmx="128g",
        )
        self.assertNotIn("--clear-pt-routes", proxy)
        physical_only = {
            item for item in fixed
            if item.startswith((
                "--taxi-dvrp-fleet=", "--taxi-dvrp-pcu=",
                "--taxi-wait-utility-per-hour=",
            ))
        }
        proxy_only = {"--fixed-plans-network-taxi-proxy"}
        self.assertEqual(physical_only, set(fixed) - set(proxy))
        self.assertEqual(proxy_only, set(proxy) - set(fixed))
        self.assertEqual(3, len(physical_only))

    def test_fleet_counter_accepts_gzip_and_rejects_wrong_immutable_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fleet = Path(directory) / "fleet.xml.gz"
            with gzip.open(fleet, "wt", encoding="utf-8") as handle:
                handle.write(
                    '<vehicles><vehicle id="1"/><dvrpVehicle id="2"/></vehicles>'
                )
            self.assertEqual(2, count_fleet_vehicles(fleet))
            plans = Path(directory) / "plans.xml.gz"
            with gzip.open(plans, "wt", encoding="utf-8") as handle:
                handle.write(
                    '<population><person id="1">'
                    '<plan selected="yes"><leg mode="taxi"/></plan>'
                    '<plan selected="no"><leg mode="taxi"/></plan></person>'
                    '<person id="2"/></population>'
                )
            self.assertEqual(2, count_population_persons(plans))
            self.assertEqual(1, audit_population(plans).taxi_legs)
            self.assertEqual(2, audit_population(plans).all_plan_taxi_legs)
        validate_run_name(Path(f"/mnt/DiskM/by/{RUN_NAME_PREFIX}20260815_run15"))
        with self.assertRaises(ValueError):
            validate_run_name(Path("/mnt/DiskM/by/run15"))


if __name__ == "__main__":
    unittest.main()
