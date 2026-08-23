#!/usr/bin/env python3
"""Prepare and launch immutable Candidate11 physical-Taxi DVRP runs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from typing import BinaryIO, Iterator


SERVER_ROOT = Path("/mnt/DiskM/by")
RUN_NAME_PREFIX = "hk_stage11_candidate11_taxi_dvrp_"
HOUSEHOLD_SELECTION_ITERATIONS = (5, 15, 25, 35)
NON_INNOVATIVE_STRATEGIES = frozenset(
    {"ChangeExpBeta", "SelectExpBeta", "KeepLastSelected"}
)
ALLOWED_TAXI_PCU = (1.0, 0.75, 0.5, 0.25, 1.0 / 6.0, 0.1, 0.05)


@dataclass(frozen=True)
class RunProfile:
    first_iteration: int
    last_iteration: int
    capacity_factor: float
    expected_fleet_size: int | None
    expected_population_size: int
    taxi_execution: str = "dvrp"
    requires_plans_override: bool = False
    fixed_selected_plans: bool = False
    traffic_signals: bool = True
    requires_network_override: bool = False
    expected_initial_taxi_legs: int | None = None
    stuck_time_s: int = 3600
    remove_stuck_vehicles: bool = False
    restored_household_bindings: int | None = None
    taxi_operational_sample_share: float = 1.0
    clear_pt_routes: bool | None = None
    taxi_operational_parent_triggered: bool = False
    mode_choice_screening: bool = False
    household_protection_only: bool = False
    scoring_arm_required: bool = False
    screening_innovation_end_iteration: int | None = None


RUN_PROFILES = {
    "formal-50": RunProfile(0, 49, 0.1, 15_500, 385_820),
    "formal-50-candidate5b": RunProfile(
        0, 49, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", fixed_selected_plans=False,
        traffic_signals=True, requires_network_override=True,
        expected_initial_taxi_legs=44_000,
    ),
    "formal-50-candidate5b-resume40": RunProfile(
        41, 49, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", requires_plans_override=True,
        fixed_selected_plans=False, traffic_signals=True,
        requires_network_override=True, restored_household_bindings=3_378,
    ),
    "score-factorial-frozen-it0": RunProfile(
        0, 0, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", fixed_selected_plans=True,
        traffic_signals=True, requires_network_override=True,
        expected_initial_taxi_legs=44_000, clear_pt_routes=True,
        scoring_arm_required=True,
    ),
    "score-factorial-10": RunProfile(
        0, 9, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", fixed_selected_plans=False,
        traffic_signals=True, requires_network_override=True,
        expected_initial_taxi_legs=44_000, clear_pt_routes=True,
        mode_choice_screening=True, household_protection_only=True,
        scoring_arm_required=True, screening_innovation_end_iteration=5,
    ),
    "score-calibration-25": RunProfile(
        0, 24, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", fixed_selected_plans=False,
        traffic_signals=True, requires_network_override=True,
        expected_initial_taxi_legs=44_000, clear_pt_routes=True,
        mode_choice_screening=True, household_protection_only=True,
        scoring_arm_required=True, screening_innovation_end_iteration=9,
    ),
    "smoke-0p5": RunProfile(
        0, 0, 0.01, 1_550, 38_582,
        taxi_execution="dvrp", requires_plans_override=True, fixed_selected_plans=True,
    ),
    "gate-0-1": RunProfile(
        0, 1, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", requires_plans_override=True, fixed_selected_plans=True,
    ),
    "gate-0-1-proxy": RunProfile(
        0, 1, 0.1, None, 385_820,
        taxi_execution="proxy", requires_plans_override=True, fixed_selected_plans=True,
    ),
    "nosignal-run7-it0": RunProfile(
        0, 0, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", requires_plans_override=True,
        fixed_selected_plans=True, traffic_signals=False,
        requires_network_override=True,
    ),
    "nosignal-run7-original-it0": RunProfile(
        0, 0, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", fixed_selected_plans=False,
        traffic_signals=False, requires_network_override=True,
        expected_initial_taxi_legs=44_000,
    ),
    "signal-candidate5b-original-it0": RunProfile(
        0, 0, 0.1, 15_500, 385_820,
        taxi_execution="dvrp", fixed_selected_plans=False,
        traffic_signals=True, requires_network_override=True,
        expected_initial_taxi_legs=44_000,
    ),
    "freeze44k-shadow6-30pct-it0": RunProfile(
        0, 0, 0.1, 4_650, 604_800,
        taxi_execution="dvrp", requires_plans_override=True,
        fixed_selected_plans=True, traffic_signals=True,
        requires_network_override=True, expected_initial_taxi_legs=262_980,
        taxi_operational_sample_share=0.30,
        clear_pt_routes=True,
    ),
    "freeze44k-tcs579011-fullfleet-it0": RunProfile(
        0, 0, 0.1, 15_500, 921_035,
        taxi_execution="dvrp", requires_plans_override=True,
        fixed_selected_plans=True, traffic_signals=True,
        requires_network_override=True, expected_initial_taxi_legs=579_215,
        taxi_operational_sample_share=1.0, clear_pt_routes=True,
        taxi_operational_parent_triggered=True,
    ),
    "freeze44k-tcs536121-fullfleet-it0": RunProfile(
        0, 0, 0.1, 15_500, 878_145,
        taxi_execution="dvrp", requires_plans_override=True,
        fixed_selected_plans=True, traffic_signals=True,
        requires_network_override=True, expected_initial_taxi_legs=536_325,
        taxi_operational_sample_share=1.0, clear_pt_routes=True,
        taxi_operational_parent_triggered=True,
    ),
    "nosignal-run7-teleported-control-it0": RunProfile(
        0, 0, 0.1, None, 385_820,
        taxi_execution="teleported", fixed_selected_plans=False,
        traffic_signals=False, requires_network_override=True,
        expected_initial_taxi_legs=44_000,
    ),
    "nosignal-run7-teleported-oldstuck-it0": RunProfile(
        0, 0, 0.1, None, 385_820,
        taxi_execution="teleported", fixed_selected_plans=False,
        traffic_signals=False, requires_network_override=True,
        expected_initial_taxi_legs=44_000,
        stuck_time_s=600, remove_stuck_vehicles=True,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an immutable Taxi experiment release/run and launch it, or "
            "stop after preparation with --prepare-only."
        )
    )
    parser.add_argument("--profile", choices=sorted(RUN_PROFILES), required=True)
    parser.add_argument("--runtime-input-release", type=Path, required=True)
    parser.add_argument("--previous-app-release", type=Path, required=True)
    parser.add_argument("--config-template", type=Path, required=True)
    parser.add_argument("--payload-jar", type=Path, required=True)
    parser.add_argument(
        "--taxi-fleet", type=Path,
        help="Required for DVRP profiles and forbidden for non-DVRP profiles.",
    )
    parser.add_argument(
        "--plans-input",
        type=Path,
        help="Override the plans file in the template; mandatory for smoke-0p5.",
    )
    parser.add_argument(
        "--network-input", type=Path,
        help="Override the network in the template; required by nosignal-run7-it0.",
    )
    parser.add_argument(
        "--transit-schedule-input", type=Path,
        help="Override the PT schedule; must be paired with --transit-vehicles-input.",
    )
    parser.add_argument(
        "--transit-vehicles-input", type=Path,
        help="Override PT vehicles; must be paired with --transit-schedule-input.",
    )
    parser.add_argument(
        "--road-supply-registry", type=Path,
        help=(
            "Optional full-network explicit storage/QSim-flow registry; "
            "requires actual Taxi PCU multiplied by the profile's operational "
            "sample share to equal 0.05."
        ),
    )
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--taxi-pcu", type=float, choices=ALLOWED_TAXI_PCU, default=1.0)
    parser.add_argument("--taxi-wait-utility-per-hour", type=float, default=-12.0)
    parser.add_argument(
        "--scoring-arm", choices=(
            "a0", "a1", "a2", "a3", "b1", "b2", "b3", "c1", "c2", "c3",
        ),
        help="Factorial Walk/Taxi scoring arm; required only by score-factorial profiles.",
    )
    parser.add_argument("--xms", default="16g")
    parser.add_argument("--xmx", default="128g")
    parser.add_argument("--prepare-only", action="store_true")
    return parser.parse_args()


def safe(path: Path, *, exists: bool) -> Path:
    result = path.resolve(strict=exists)
    if result == SERVER_ROOT or SERVER_ROOT not in result.parents:
        raise ValueError(f"Path must be below {SERVER_ROOT}: {result}")
    return result


def validate_run_name(path: Path) -> None:
    if not path.name.startswith(RUN_NAME_PREFIX):
        raise ValueError(
            f"Immutable release/run name must start with {RUN_NAME_PREFIX!r}: {path}"
        )


def module(root: ET.Element, name: str) -> ET.Element:
    found = [item for item in root.findall("./module") if item.get("name") == name]
    if len(found) != 1:
        raise ValueError(f"Expected exactly one module {name}; found {len(found)}")
    return found[0]


def set_param(parent: ET.Element, name: str, value: str) -> None:
    found = [item for item in parent.findall("./param") if item.get("name") == name]
    if len(found) > 1:
        raise ValueError(f"Duplicate parameter {name}")
    item = found[0] if found else ET.SubElement(parent, "param")
    item.set("name", name)
    item.set("value", value)


def strategy_name(settings: ET.Element) -> str:
    names = [
        item.get("value", "")
        for item in settings.findall("./param")
        if item.get("name") == "strategyName"
    ]
    if len(names) != 1 or not names[0]:
        raise ValueError("Each strategysettings block must have one strategyName")
    return names[0]


def freeze_innovation_after_iteration(replanning: ET.Element, iteration: int) -> list[str]:
    frozen: list[str] = []
    strategies = replanning.findall("./parameterset[@type='strategysettings']")
    if not strategies:
        raise ValueError("The replanning module has no strategysettings blocks")
    for settings in strategies:
        name = strategy_name(settings)
        if name in NON_INNOVATIVE_STRATEGIES:
            # Remove a stale disable setting from selection-only strategies.
            for item in list(settings.findall("./param")):
                if item.get("name") == "disableAfterIteration":
                    settings.remove(item)
            continue
        set_param(settings, "disableAfterIteration", str(iteration))
        frozen.append(name)
    if not frozen:
        raise ValueError("No innovative strategy was found to freeze")
    return sorted(set(frozen))


def keep_last_selected_only(replanning: ET.Element) -> list[str]:
    strategies = replanning.findall("./parameterset[@type='strategysettings']")
    if not strategies:
        raise ValueError("The replanning module has no strategysettings blocks")
    by_subpopulation: dict[str, list[ET.Element]] = {}
    removed: list[str] = []
    for settings in strategies:
        parameters = {
            item.get("name", ""): item.get("value", "")
            for item in settings.findall("./param")
        }
        by_subpopulation.setdefault(parameters.get("subpopulation", ""), []).append(settings)
    for blocks in by_subpopulation.values():
        keep = next(
            (item for item in blocks if strategy_name(item) == "KeepLastSelected"),
            blocks[0],
        )
        for settings in blocks:
            name = strategy_name(settings)
            if settings is not keep:
                removed.append(name)
                replanning.remove(settings)
        for item in keep.findall("./param"):
            if item.get("name") == "strategyName":
                item.set("value", "KeepLastSelected")
            elif item.get("name") == "weight":
                item.set("value", "1.0")
        set_param(keep, "weight", "1.0")
        for item in list(keep.findall("./param")):
            if item.get("name") == "disableAfterIteration":
                keep.remove(item)
    return sorted(set(removed))


def mode_choice_screening_only(
    replanning: ET.Element, innovation_end_iteration: int,
) -> list[str]:
    """Keep protected people frozen and bound ordinary mode innovation."""
    if innovation_end_iteration < 0:
        raise ValueError("Screening innovation end iteration must be non-negative")
    strategies = replanning.findall("./parameterset[@type='strategysettings']")
    if not strategies:
        raise ValueError("The replanning module has no strategysettings blocks")
    by_subpopulation: dict[str, list[ET.Element]] = {}
    for settings in strategies:
        parameters = {
            item.get("name", ""): item.get("value", "")
            for item in settings.findall("./param")
        }
        by_subpopulation.setdefault(parameters.get("subpopulation", ""), []).append(settings)

    removed: list[str] = []
    for subpopulation, blocks in by_subpopulation.items():
        protected = subpopulation == "hk_household_student_protected"
        no_car_border = subpopulation == "hk_unpriced_border_no_car_mode_innovation"
        keep_names = (
            {"KeepLastSelected"} if protected
            else {"ChangeExpBeta"} if no_car_border
            else {"ChangeExpBeta", "SubtourModeChoice"}
        )
        kept: dict[str, ET.Element] = {}
        for settings in blocks:
            name = strategy_name(settings)
            if name not in keep_names or name in kept:
                removed.append(name)
                replanning.remove(settings)
                continue
            kept[name] = settings
        if set(kept) != keep_names:
            raise ValueError(
                f"Missing screening strategy for {subpopulation!r}: "
                f"required={sorted(keep_names)}, found={sorted(kept)}"
            )
        for name, settings in kept.items():
            set_param(settings, "weight", (
                "1.0" if protected or no_car_border
                else "0.8" if name == "ChangeExpBeta" else "0.2"
            ))
            for item in list(settings.findall("./param")):
                if item.get("name") == "disableAfterIteration":
                    settings.remove(item)
            if name == "SubtourModeChoice":
                set_param(
                    settings, "disableAfterIteration", str(innovation_end_iteration),
                )
    return sorted(set(removed))


def derive_config(
    template: Path,
    destination: Path,
    run: Path,
    profile: RunProfile,
    *,
    plans_input: Path | None = None,
    network_input: Path | None = None,
    transit_schedule_input: Path | None = None,
    transit_vehicles_input: Path | None = None,
) -> list[str]:
    tree = ET.parse(template)
    root = tree.getroot()
    routing = module(root, "routing")
    walk_speed = None
    for parameterset in routing.findall("./parameterset"):
        if parameterset.get("type") != "teleportedModeParameters":
            continue
        values = {
            param.get("name"): param.get("value")
            for param in parameterset.findall("./param")
        }
        if values.get("mode") == "walk":
            walk_speed = values.get("teleportedModeSpeed")
            break
    if walk_speed in (None, "", "null"):
        raise ValueError(
            "Config template must be a pre-run config containing the Walk "
            "teleportedModeSpeed; output/output_config.xml is post-mutation and "
            "cannot be reused as the Candidate11 Taxi/DVRP template."
        )
    set_param(module(root, "global"), "numberOfThreads", "16")

    qsim = module(root, "qsim")
    set_param(qsim, "numberOfThreads", "16")
    set_param(qsim, "flowCapacityFactor", str(profile.capacity_factor))
    set_param(qsim, "storageCapacityFactor", str(profile.capacity_factor))
    set_param(qsim, "stuckTime", str(profile.stuck_time_s))
    set_param(
        qsim, "removeStuckVehicles",
        "true" if profile.remove_stuck_vehicles else "false",
    )
    if profile.taxi_execution == "dvrp":
        set_param(qsim, "simStarttimeInterpretation", "onlyUseStarttime")
    if profile.traffic_signals:
        set_param(qsim, "usingFastCapacityUpdate", "false")

    controller = module(root, "controller")
    updates = {
        "firstIteration": str(profile.first_iteration),
        "lastIteration": str(profile.last_iteration),
        "outputDirectory": str(run / "output"),
        "overwriteFiles": "failIfDirectoryExists",
        "createGraphsInterval": "10",
        "legDurationsInterval": "10",
        "legHistogramInterval": "10",
        "writeTripsInterval": "1" if profile.mode_choice_screening else "10",
        "writeEventsInterval": "10",
        "writePlansInterval": "1" if profile.mode_choice_screening else "10",
        "writeSnapshotsInterval": "0",
        "createScoringFunctionType": "BeforeMobsim",
    }
    for name, value in updates.items():
        set_param(controller, name, value)
    set_param(module(root, "scoring"), "writeExperiencedPlans", "true")

    replanning = module(root, "replanning")
    if profile.fixed_selected_plans:
        set_param(replanning, "fractionOfIterationsToDisableInnovation", "0.0")
        frozen_strategies = keep_last_selected_only(replanning)
    elif profile.mode_choice_screening:
        set_param(replanning, "fractionOfIterationsToDisableInnovation", "0.4")
        if profile.screening_innovation_end_iteration is None:
            raise ValueError("Mode-choice screening profile lacks an innovation cutoff")
        frozen_strategies = mode_choice_screening_only(
            replanning, profile.screening_innovation_end_iteration,
        )
    else:
        set_param(replanning, "fractionOfIterationsToDisableInnovation", "0.70")
        frozen_strategies = freeze_innovation_after_iteration(replanning, 34)

    subtour = module(root, "subtourModeChoice")
    set_param(subtour, "modes", "car,pt,walk,taxi")
    set_param(subtour, "chainBasedModes", "car")
    if plans_input is not None:
        set_param(module(root, "plans"), "inputPlansFile", str(plans_input))
    if network_input is not None:
        set_param(module(root, "network"), "inputNetworkFile", str(network_input))
    if (transit_schedule_input is None) != (transit_vehicles_input is None):
        raise ValueError("PT schedule and vehicle overrides must be supplied together")
    if transit_schedule_input is not None and transit_vehicles_input is not None:
        transit = module(root, "transit")
        set_param(transit, "transitScheduleFile", str(transit_schedule_input))
        set_param(transit, "vehiclesFile", str(transit_vehicles_input))
    set_param(
        module(root, "signalsystems"), "useSignalsystems",
        "true" if profile.traffic_signals else "false",
    )

    destination.parent.mkdir(parents=True, exist_ok=False)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("<?xml version='1.0' encoding='utf-8'?>\n")
        handle.write('<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n')
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")
    ET.parse(destination)
    return frozen_strategies


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def count_fleet_vehicles(path: Path) -> int:
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    count = 0
    with opener(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag.rsplit("}", 1)[-1] in {"vehicle", "dvrpVehicle"}:
                count += 1
            element.clear()
    return count


@contextmanager
def open_xml_binary(path: Path) -> Iterator[BinaryIO]:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
        return
    if path.suffix.lower() != ".zst":
        with path.open("rb") as handle:
            yield handle
        return
    executable = Path("/usr/bin/zstdcat")
    if not executable.is_file():
        raise ValueError(f"Cannot audit Zstandard XML without {executable}: {path}")
    process = subprocess.Popen(
        [str(executable), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert process.stdout is not None
    try:
        yield process.stdout
    except BaseException:
        process.terminate()
        process.wait()
        raise
    finally:
        process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    return_code = process.wait()
    if return_code != 0:
        raise ValueError(f"zstdcat failed for {path}: {stderr.strip()}")


@dataclass(frozen=True)
class PopulationAudit:
    persons: int
    taxi_legs: int


def audit_population(path: Path) -> PopulationAudit:
    persons = 0
    taxi_legs = 0
    with open_xml_binary(path) as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            name = element.tag.rsplit("}", 1)[-1]
            if name == "person":
                persons += 1
            elif name == "leg" and element.get("mode") == "taxi":
                taxi_legs += 1
            element.clear()
    return PopulationAudit(persons, taxi_legs)


@dataclass(frozen=True)
class RoadSupplyRegistryAudit:
    road_links: int
    storage_overrides: int
    flow_overrides: int


def audit_road_supply_registry(path: Path) -> RoadSupplyRegistryAudit:
    road_links = 0
    storage_overrides = 0
    flow_overrides = 0
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "link_id", "storage_capacity_override", "flow_capacity_override"
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"Road-supply registry lacks required columns: {path}")
        for row in reader:
            road_links += 1
            storage_overrides += row["storage_capacity_override"].lower() == "true"
            flow_overrides += row["flow_capacity_override"].lower() == "true"
    if road_links == 0 or storage_overrides == 0:
        raise ValueError(
            "Road-supply registry must contain road links and storage overrides: "
            f"{path}"
        )
    return RoadSupplyRegistryAudit(road_links, storage_overrides, flow_overrides)


def count_population_persons(path: Path) -> int:
    return audit_population(path).persons


def plans_path_from_template(template: Path) -> Path:
    root = ET.parse(template).getroot()
    plans = module(root, "plans")
    values = [
        item.get("value", "")
        for item in plans.findall("./param")
        if item.get("name") == "inputPlansFile"
    ]
    if len(values) != 1 or not values[0]:
        raise ValueError("Template must define exactly one plans inputPlansFile")
    result = Path(values[0])
    if not result.is_absolute():
        result = template.parent / result
    return result


def build_command(
    *,
    java: Path,
    jar: Path,
    config: Path,
    cost_root: Path,
    runtime: Path,
    fleet: Path | None,
    taxi_pcu: float,
    taxi_wait_utility_per_hour: float,
    profile: RunProfile,
    xms: str,
    xmx: str,
    road_supply_registry: Path | None = None,
    scoring_arm: str | None = None,
) -> list[str]:
    command = [
        str(java), f"-Xms{xms}", f"-Xmx{xmx}", "-cp", str(jar),
        "org.matsim.project.RunHongKong5Pct", str(config), "unused",
        "--simulate", "--multimodal-costs", "--dynamic-car-costs",
        f"--pt-fare-root={cost_root / 'pt_fare_v1'}",
        f"--car-cost-root={cost_root / 'car_cost_v1'}",
        "--physical-nontaxi-modes", "--unlimited-ordinary-pt-capacity",
        f"--student-school-mode-candidates={runtime / 'input/school_bus_plan_candidates_5pct_v6'}",
    ]
    if profile.taxi_execution != "teleported":
        command.append("--walk-overtime-scoring")
    if scoring_arm in {"a2", "a3", "b1", "c1"}:
        command.append("--walk-scoring-profile=calibration-v2")
    elif scoring_arm in {"b2", "b3"}:
        command.append("--walk-scoring-profile=calibration-v3")
    elif scoring_arm in {"c2", "c3"}:
        command.append("--walk-scoring-profile=calibration-v4")
    if profile.traffic_signals:
        command.append("--traffic-signals")
    # Fixed gate/smoke plans are experienced physical itineraries from run14b.
    # Clearing their valid PT routes would discard that frozen network state and
    # can split a school-bus trip into inconsistent per-leg routing modes.  The
    # formal profile starts from the original generic Candidate11 plans, so it
    # still requires the established SwissRailRaptor rebuild.
    clear_pt_routes = (
        not profile.fixed_selected_plans
        if profile.clear_pt_routes is None
        else profile.clear_pt_routes
    )
    if clear_pt_routes:
        command.append("--clear-pt-routes")
    if profile.taxi_execution == "dvrp":
        if fleet is None:
            raise ValueError("A Taxi fleet is required for DVRP command construction")
        taxi_pcu_text = (
            f"{taxi_pcu:.17g}"
            if math.isclose(taxi_pcu, 1.0 / 6.0, rel_tol=0.0, abs_tol=1e-15)
            else f"{taxi_pcu:g}"
        )
        command.extend([
            f"--taxi-dvrp-fleet={fleet}",
            f"--taxi-dvrp-pcu={taxi_pcu_text}",
            f"--taxi-wait-utility-per-hour={taxi_wait_utility_per_hour:g}",
        ])
        if scoring_arm in {"a1", "a3", "b2", "c2"}:
            command.extend([
                "--taxi-adult-fare-utility-per-hkd=0.12",
                "--taxi-student-fare-utility-per-hkd=0.18",
            ])
        elif scoring_arm in {"b1", "b3"}:
            command.extend([
                "--taxi-constant-per-trip=-9.6",
                "--taxi-adult-fare-utility-per-hkd=0.125",
                "--taxi-student-fare-utility-per-hkd=0.1875",
            ])
        elif scoring_arm in {"c1", "c3"}:
            command.extend([
                "--taxi-constant-per-trip=-9.6",
                "--taxi-adult-fare-utility-per-hkd=1",
                "--taxi-student-fare-utility-per-hkd=1",
            ])
        if not math.isclose(profile.taxi_operational_sample_share, 1.0):
            command.append(
                "--taxi-operational-sample-share="
                f"{profile.taxi_operational_sample_share:g}"
            )
        if road_supply_registry is not None:
            command.append(f"--road-supply-registry={road_supply_registry}")
        if profile.taxi_operational_parent_triggered:
            command.append("--taxi-operational-parent-triggered")
    elif profile.taxi_execution == "proxy":
        if fleet is not None:
            raise ValueError("Proxy command construction must not receive a Taxi fleet")
        command.append("--fixed-plans-network-taxi-proxy")
    elif profile.taxi_execution == "teleported":
        if fleet is not None:
            raise ValueError("Teleported control must not receive a Taxi fleet")
        # This control runs only iteration 0 from the untouched Candidate11
        # plans.  Do not load either Taxi innovation or the household selector:
        # neither can affect the requested frozen QSim, and the household
        # validation intentionally rejects the ordinary ChangeExpBeta selector
        # still present in the source configuration.
        return command
    else:
        raise ValueError(f"Unsupported Taxi execution: {profile.taxi_execution}")
    if profile.household_protection_only:
        command.append(
            f"--household-joint-plan-candidates={runtime / 'input/household_joint_plan_potential_candidates.csv'}"
        )
        command.append("--household-joint-protection-only")
    elif not profile.fixed_selected_plans:
        command.append(
            f"--household-joint-plan-candidates={runtime / 'input/household_joint_plan_potential_candidates.csv'}"
        )
        command.append("--household-joint-plan-with-ordinary-innovation")
        active_selection_iterations = tuple(
            iteration for iteration in HOUSEHOLD_SELECTION_ITERATIONS
            if profile.first_iteration <= iteration <= profile.last_iteration
        )
        if active_selection_iterations:
            command.append(
                "--household-joint-selection-iterations="
                + ",".join(map(str, active_selection_iterations))
            )
        if "--all-person-network-taxi-innovation" not in command:
            command.append("--all-person-network-taxi-innovation")
        if profile.restored_household_bindings is not None:
            command.append(
                "--household-joint-restore-selected-bindings="
                + str(profile.restored_household_bindings)
            )
    return command


def main() -> int:
    args = parse_args()
    profile = RUN_PROFILES[args.profile]
    if profile.scoring_arm_required != (args.scoring_arm is not None):
        raise ValueError(
            f"Profile {args.profile} scoring-arm requirement is "
            f"{profile.scoring_arm_required}; received {args.scoring_arm!r}"
        )
    if args.scoring_arm is not None and args.taxi_wait_utility_per_hour != -12.0:
        raise ValueError(
            "Factorial profiles derive the Taxi wait coefficient from --scoring-arm; "
            "do not also override --taxi-wait-utility-per-hour"
        )
    effective_taxi_wait_utility = (
        -6.0 if args.scoring_arm in {"c1", "c3"}
        else -18.0 if args.scoring_arm in {"a1", "a3", "b1", "b2", "b3", "c2"}
        else args.taxi_wait_utility_per_hour
    )
    if profile.requires_plans_override and args.plans_input is None:
        raise ValueError(f"--plans-input is required for profile {args.profile}")
    if profile.requires_network_override and args.network_input is None:
        raise ValueError(f"--network-input is required for profile {args.profile}")
    if not profile.requires_network_override and args.network_input is not None:
        raise ValueError(f"--network-input is forbidden for profile {args.profile}")
    if args.profile in {
        "formal-50", "formal-50-candidate5b",
        "nosignal-run7-original-it0",
        "signal-candidate5b-original-it0",
        "score-factorial-frozen-it0", "score-factorial-10", "score-calibration-25",
        "nosignal-run7-teleported-control-it0",
        "nosignal-run7-teleported-oldstuck-it0",
    } \
            and args.plans_input is not None:
        raise ValueError(
            f"{args.profile} must use the original Candidate11 plans from the template"
        )
    if profile.taxi_execution == "dvrp" and args.taxi_fleet is None:
        raise ValueError(f"--taxi-fleet is required for profile {args.profile}")
    if profile.taxi_execution != "dvrp" and args.taxi_fleet is not None:
        raise ValueError(f"--taxi-fleet is forbidden for profile {args.profile}")
    if profile.taxi_execution != "dvrp" and (
        args.taxi_pcu != 1.0 or args.taxi_wait_utility_per_hour != -12.0
    ):
        raise ValueError("Non-DVRP profiles do not accept Taxi DVRP PCU/wait overrides")
    if effective_taxi_wait_utility >= 0:
        raise ValueError("Taxi wait utility per hour must be negative")
    equivalent_taxi_pcu = args.taxi_pcu * profile.taxi_operational_sample_share
    if args.road_supply_registry is not None and (
        profile.taxi_execution != "dvrp"
        or not math.isclose(equivalent_taxi_pcu, 0.05, rel_tol=0.0, abs_tol=1e-9)
    ):
        raise ValueError(
            "--road-supply-registry requires DVRP Taxi actual PCU multiplied by "
            "operational sample share to equal the registry basis 0.05"
        )
    if args.road_supply_registry is not None and args.network_input is None:
        raise ValueError("--road-supply-registry requires --network-input")
    if (args.transit_schedule_input is None) != (args.transit_vehicles_input is None):
        raise ValueError(
            "--transit-schedule-input and --transit-vehicles-input must be supplied together"
        )

    runtime = safe(args.runtime_input_release, exists=True)
    previous = safe(args.previous_app_release, exists=True)
    template = safe(args.config_template, exists=True)
    payload_jar = safe(args.payload_jar, exists=True)
    source_fleet = safe(args.taxi_fleet, exists=True) if args.taxi_fleet else None
    plans_input = safe(args.plans_input, exists=True) if args.plans_input else None
    source_network = safe(args.network_input, exists=True) if args.network_input else None
    source_transit_schedule = (
        safe(args.transit_schedule_input, exists=True)
        if args.transit_schedule_input else None
    )
    source_transit_vehicles = (
        safe(args.transit_vehicles_input, exists=True)
        if args.transit_vehicles_input else None
    )
    source_road_supply_registry = (
        safe(args.road_supply_registry, exists=True)
        if args.road_supply_registry else None
    )
    road_supply_audit = (
        audit_road_supply_registry(source_road_supply_registry)
        if source_road_supply_registry is not None else None
    )
    effective_plans = plans_input or safe(
        plans_path_from_template(template), exists=True
    )
    release = safe(args.release_root, exists=False)
    run = safe(args.run_root, exists=False)
    validate_run_name(release)
    validate_run_name(run)
    if release.exists() or run.exists():
        raise FileExistsError("Release and run roots must both be absent")

    required_files = [
        runtime / "runtime/jdk-25/bin/java",
        template,
        payload_jar,
    ]
    if source_fleet is not None:
        required_files.append(source_fleet)
    if source_network is not None:
        required_files.append(source_network)
    if source_transit_schedule is not None:
        required_files.append(source_transit_schedule)
    if source_transit_vehicles is not None:
        required_files.append(source_transit_vehicles)
    if source_road_supply_registry is not None:
        required_files.append(source_road_supply_registry)
    if (
        (not profile.fixed_selected_plans or profile.household_protection_only)
        and profile.taxi_execution != "teleported"
    ):
        required_files.append(
            runtime / "input/household_joint_plan_potential_candidates.csv"
        )
    for required in required_files:
        if not required.is_file() or required.is_symlink():
            raise ValueError(f"Required regular file is missing: {required}")
    pt_source = runtime / "data/transport_costs/hongkong/pt_fare_v1"
    car_source = previous / "data/transport_costs/hongkong/car_cost_v1"
    required_directories = [
        pt_source,
        car_source,
        runtime / "input/school_bus_plan_candidates_5pct_v6",
    ]
    for required in required_directories:
        if not required.is_dir() or required.is_symlink():
            raise ValueError(f"Required directory is missing: {required}")

    actual_fleet_size = None
    if source_fleet is not None:
        actual_fleet_size = count_fleet_vehicles(source_fleet)
        if actual_fleet_size != profile.expected_fleet_size:
            raise ValueError(
                f"Profile {args.profile} requires {profile.expected_fleet_size} Taxi vehicles; "
                f"found {actual_fleet_size} in {source_fleet}"
            )
    population_audit = audit_population(effective_plans)
    if population_audit.persons != profile.expected_population_size:
        raise ValueError(
            f"Profile {args.profile} requires {profile.expected_population_size} persons; "
            f"found {population_audit.persons} in {effective_plans}"
        )
    if profile.fixed_selected_plans and population_audit.taxi_legs == 0:
        raise ValueError(
            f"Profile {args.profile} requires stable selected plans containing Taxi legs: "
            f"{effective_plans}"
        )
    if profile.expected_initial_taxi_legs is not None \
            and population_audit.taxi_legs != profile.expected_initial_taxi_legs:
        raise ValueError(
            f"Profile {args.profile} requires {profile.expected_initial_taxi_legs} "
            f"initial Taxi legs; found {population_audit.taxi_legs} in {effective_plans}"
        )

    release.mkdir()
    (release / "app").mkdir()
    jar = release / "app/matsim-example-project-0.0.1-SNAPSHOT.jar"
    shutil.copy2(payload_jar, jar)
    fleet = None
    if source_fleet is not None:
        (release / "input").mkdir()
        fleet_suffix = ".xml.gz" if source_fleet.suffix.lower() == ".gz" else ".xml"
        fleet = release / f"input/taxi_fleet{fleet_suffix}"
        shutil.copy2(source_fleet, fleet)
    network = None
    if source_network is not None:
        (release / "input").mkdir(exist_ok=True)
        network_suffix = ".xml.gz" if source_network.suffix.lower() == ".gz" else ".xml"
        network = release / f"input/network{network_suffix}"
        shutil.copy2(source_network, network)
    road_supply_registry = None
    if source_road_supply_registry is not None:
        (release / "input").mkdir(exist_ok=True)
        road_supply_registry = release / f"input/{source_road_supply_registry.name}"
        shutil.copy2(source_road_supply_registry, road_supply_registry)
    transit_schedule = None
    transit_vehicles = None
    if source_transit_schedule is not None and source_transit_vehicles is not None:
        (release / "input").mkdir(exist_ok=True)
        schedule_suffix = ".xml.gz" if source_transit_schedule.suffix.lower() == ".gz" else ".xml"
        vehicles_suffix = ".xml.gz" if source_transit_vehicles.suffix.lower() == ".gz" else ".xml"
        transit_schedule = release / f"input/transitSchedule{schedule_suffix}"
        transit_vehicles = release / f"input/transitVehicles{vehicles_suffix}"
        shutil.copy2(source_transit_schedule, transit_schedule)
        shutil.copy2(source_transit_vehicles, transit_vehicles)
    cost_root = release / "data/transport_costs/hongkong"
    cost_root.mkdir(parents=True)
    shutil.copytree(pt_source, cost_root / "pt_fare_v1")
    shutil.copytree(car_source, cost_root / "car_cost_v1")
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    config = run / f"config_candidate11_taxi_dvrp_{args.profile}.xml"
    frozen_strategies = derive_config(
        template, config, run, profile, plans_input=plans_input,
        network_input=network,
        transit_schedule_input=transit_schedule,
        transit_vehicles_input=transit_vehicles,
    )
    java = runtime / "runtime/jdk-25/bin/java"
    command = build_command(
        java=java,
        jar=jar,
        config=config,
        cost_root=cost_root,
        runtime=runtime,
        fleet=fleet,
        road_supply_registry=road_supply_registry,
        taxi_pcu=args.taxi_pcu,
        taxi_wait_utility_per_hour=effective_taxi_wait_utility,
        profile=profile,
        scoring_arm=args.scoring_arm,
        xms=args.xms,
        xmx=args.xmx,
    )
    worker = run / "worker.sh"
    worker.write_text(
        "#!/usr/bin/env bash\nset -u\n"
        f"cd {shlex.quote(str(run))}\n"
        f"export HOME={shlex.quote(str(release / 'home'))}\n"
        f"export TMPDIR={shlex.quote(str(release / 'tmp'))}\n"
        f"export XDG_CACHE_HOME={shlex.quote(str(release / 'home/.cache'))}\n"
        f"/usr/bin/time -v {shell_join(command)}\n"
        "rc=$?\nprintf '%s\\n' \"$rc\" > exit_code.txt\n"
        "date --iso-8601=seconds > finished_at.txt\nexit \"$rc\"\n",
        encoding="utf-8", newline="\n",
    )
    worker.chmod(worker.stat().st_mode | stat.S_IXUSR)

    metadata = {
        "objective": (
            "Candidate11 physical Taxi DVRP with explicit fleet matching and waiting"
            if profile.taxi_execution == "dvrp"
            else "Candidate11 no-physical-Taxi control with teleported Taxi"
        ),
        "profile": args.profile,
        "qsim_iterations": list(
            range(profile.first_iteration, profile.last_iteration + 1)
        ),
        "global_threads": 16,
        "qsim_threads": 16,
        "flow_capacity_factor": profile.capacity_factor,
        "storage_capacity_factor": profile.capacity_factor,
        "stuck_time_s": profile.stuck_time_s,
        "remove_stuck_vehicles": profile.remove_stuck_vehicles,
        "output_interval": 10,
        "fixed_selected_plans": profile.fixed_selected_plans,
        "traffic_signals": profile.traffic_signals,
        "taxi_execution": profile.taxi_execution,
        "innovation_disable_after_iteration": (
            None if profile.fixed_selected_plans
            else profile.screening_innovation_end_iteration
            if profile.mode_choice_screening else 34
        ),
        "fraction_of_iterations_to_disable_innovation": (
            0.0 if profile.fixed_selected_plans
            else 0.4 if profile.mode_choice_screening else 0.70
        ),
        "frozen_innovative_strategies": (
            [] if profile.fixed_selected_plans
            else ["SubtourModeChoice"] if profile.mode_choice_screening
            else frozen_strategies
        ),
        "removed_replanning_strategies": (
            frozen_strategies
            if profile.fixed_selected_plans or profile.mode_choice_screening else []
        ),
        "protected_selection_target_iterations": (
            [] if profile.fixed_selected_plans or profile.household_protection_only else [
                iteration for iteration in HOUSEHOLD_SELECTION_ITERATIONS
                if profile.first_iteration <= iteration <= profile.last_iteration
            ]
        ),
        "household_joint_catalog_loaded": (
            (not profile.fixed_selected_plans or profile.household_protection_only)
            and profile.taxi_execution != "teleported"
        ),
        "household_protection_only": profile.household_protection_only,
        "mode_choice_screening": profile.mode_choice_screening,
        "scoring_arm": args.scoring_arm,
        "scoring_parameters": (
            {
                "walk": (
                    {
                        "version": "calibration-v2",
                        "constant_per_main_walk_trip": -0.15,
                        "first_threshold_s": 600.0,
                        "first_slope_util_per_h": -3.278342,
                        "second_threshold_s": 900.0,
                        "second_slope_util_per_h": -9.0,
                        "main_walk_trips_only": True,
                    }
                    if args.scoring_arm in {"a2", "a3", "b1", "c1"}
                    else (
                        {
                            "version": "calibration-v3",
                            "constant_per_main_walk_trip": 0.20,
                            "first_threshold_s": 600.0,
                            "first_slope_util_per_h": -3.278342,
                            "second_threshold_s": 900.0,
                            "second_slope_util_per_h": -12.0,
                            "third_threshold_s": 1_800.0,
                            "third_slope_util_per_h": -60.0,
                            "main_walk_trips_only": True,
                        }
                        if args.scoring_arm in {"b2", "b3"}
                        else (
                            {
                                "version": "calibration-v4",
                                "constant_per_main_walk_trip": 2.0,
                                "first_threshold_s": 600.0,
                                "first_slope_util_per_h": -3.278342,
                                "second_threshold_s": 900.0,
                                "second_slope_util_per_h": -60.0,
                                "third_threshold_s": 1_800.0,
                                "third_slope_util_per_h": -240.0,
                                "main_walk_trips_only": True,
                            }
                            if args.scoring_arm in {"c2", "c3"}
                            else {"version": "legacy-v1"}
                        )
                    )
                ),
                "taxi": (
                    {
                        "version": "calibration-v2",
                        "constant_per_trip": -9.0,
                        "in_vehicle_utility_per_h": -6.0,
                        "wait_utility_per_h": -18.0,
                        "adult_fare_utility_per_hkd": -0.12,
                        "student_fare_utility_per_hkd": -0.18,
                    }
                    if args.scoring_arm in {"a1", "a3", "b2", "c2"}
                    else (
                        {
                            "version": "calibration-v3",
                            "constant_per_trip": -9.6,
                            "in_vehicle_utility_per_h": -6.0,
                            "wait_utility_per_h": -18.0,
                            "adult_fare_utility_per_hkd": -0.125,
                            "student_fare_utility_per_hkd": -0.1875,
                        }
                        if args.scoring_arm in {"b1", "b3"}
                        else (
                            {
                                "version": "pt-aligned-cost-v4",
                                "constant_per_trip": -9.6,
                                "in_vehicle_utility_per_h": -6.0,
                                "wait_utility_per_h": -6.0,
                                "adult_fare_utility_per_hkd": -1.0,
                                "student_fare_utility_per_hkd": -1.0,
                            }
                            if args.scoring_arm in {"c1", "c3"}
                            else {"version": "formal50-v1"}
                        )
                    )
                ),
            }
            if args.scoring_arm is not None else None
        ),
        "student_school_catalog_loaded": True,
        "taxi": (
            {
                "execution": "dvrp",
                "fleet_size": actual_fleet_size,
                "pcu": args.taxi_pcu,
                "operational_sample_share": profile.taxi_operational_sample_share,
                "operational_parent_triggered": profile.taxi_operational_parent_triggered,
                "full_fleet_equivalent_pcu": equivalent_taxi_pcu,
                "wait_utility_per_hour": effective_taxi_wait_utility,
                "fleet_source": str(source_fleet),
                "fleet_source_sha256": sha256(source_fleet),
                "fleet_release_copy": str(fleet),
                "fleet_release_sha256": sha256(fleet),
            }
            if source_fleet is not None and fleet is not None
            else {
                "execution": profile.taxi_execution,
                "fleet_size": None,
                "pcu": 1.0 if profile.taxi_execution == "proxy" else None,
                "wait_utility_per_hour": None,
                "execution_contract": (
                    "person-local network Taxi; no cruising/deadheading/fleet matching"
                    if profile.taxi_execution == "proxy"
                    else "teleported Taxi; no Taxi vehicle enters QSim"
                ),
            }
        ),
        "plans": {
            "effective_input": str(effective_plans),
            "override": str(plans_input) if plans_input else None,
            "population_size": population_audit.persons,
            "taxi_legs_in_plan_memory": population_audit.taxi_legs,
            "sha256": sha256(effective_plans),
        },
        "network": (
            {
                "override_source": str(source_network),
                "override_source_sha256": sha256(source_network),
                "release_copy": str(network),
                "release_copy_sha256": sha256(network),
            }
            if source_network is not None and network is not None
            else {"override_source": None}
        ),
        "road_supply_registry": (
            {
                "enabled": True,
                "source": str(source_road_supply_registry),
                "source_sha256": sha256(source_road_supply_registry),
                "release_copy": str(road_supply_registry),
                "release_copy_sha256": sha256(road_supply_registry),
                "road_links": road_supply_audit.road_links,
                "storage_override_links": road_supply_audit.storage_overrides,
                "flow_override_links": road_supply_audit.flow_overrides,
                "storage_override_contract": (
                    "S=max(registry storage floor,physical default,queue safety)"
                ),
                "flow_override_contract": (
                    "per-link QSim-only override; physical scenario network unchanged"
                    if road_supply_audit.flow_overrides
                    else "none; physical network flow capacities unchanged"
                ),
            }
            if source_road_supply_registry is not None and road_supply_registry is not None
            else {"enabled": False}
        ),
        "transit_supply": (
            {
                "override_enabled": True,
                "schedule_source": str(source_transit_schedule),
                "schedule_source_sha256": sha256(source_transit_schedule),
                "schedule_release_copy": str(transit_schedule),
                "schedule_release_sha256": sha256(transit_schedule),
                "vehicles_source": str(source_transit_vehicles),
                "vehicles_source_sha256": sha256(source_transit_vehicles),
                "vehicles_release_copy": str(transit_vehicles),
                "vehicles_release_sha256": sha256(transit_vehicles),
            }
            if source_transit_schedule is not None
            and source_transit_vehicles is not None
            and transit_schedule is not None
            and transit_vehicles is not None
            else {"override_enabled": False}
        ),
        "runtime_input_release": str(runtime),
        "previous_app_release": str(previous),
        "pt_fare_source": str(pt_source),
        "car_cost_source": str(car_source),
        "payload_jar_source": str(payload_jar),
        "payload_jar_sha256": sha256(payload_jar),
        "release_root": str(release),
        "run_root": str(run),
        "command": command,
        "prepared_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "prepare_only": args.prepare_only,
    }
    metadata_path = run / "run_metadata.json"
    if args.prepare_only:
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "PREPARED", **metadata}, indent=2))
        return 0

    metadata["started_at"] = datetime.now(timezone.utc).astimezone().isoformat()
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log = (run / "run_stdout_stderr.log").open("x", encoding="utf-8")
    process = subprocess.Popen(
        [str(worker)], cwd=run, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    (run / "launcher_pid.txt").write_text(f"{process.pid}\n", encoding="ascii")
    print(json.dumps({"status": "STARTED", "pid": process.pid, **metadata}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
