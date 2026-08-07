#!/usr/bin/env python3
"""Launch the fixed school-escort physical or one-shot JointReRoute pilot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

from launch_hong_kong_stage11_direct_10it import (
    BASE_INPUT_PATHS,
    freeze_canonical_plan_innovation,
    require_canonical_plan_innovation_frozen,
    require_physical_transit_modes,
    require_pt_teleported_routing,
    require_regular,
    require_scoring_function_creation_after_replanning,
    require_taxi_scoring_contract,
    require_car_passenger_time_only,
    safe_server_path,
    set_car_distance_rate_zero,
    set_physical_transit_modes,
    set_pt_teleported_routing,
    set_scoring_function_creation_after_replanning,
    set_taxi_scoring_contract,
    set_car_passenger_time_only,
    shell_join,
    write_run_config,
)


EXPECTED_BINDING_ROWS = 278
EXPECTED_ENDOGENOUS_BINDING_ROWS = 384


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-release", type=Path, required=True)
    parser.add_argument("--config-template", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--xms", default="16g")
    parser.add_argument("--xmx", default="96g")
    parser.add_argument(
        "--joint-reroute",
        action="store_true",
        help=(
            "Run it.0, reroute only the fixed bound driver Car legs once, then "
            "validate physical binding in it.1. The fixed-route multimodal cost "
            "module is deliberately excluded."
        ),
    )
    parser.add_argument(
        "--dynamic-car-costs",
        action="store_true",
        help=(
            "Enable route/event-based Car energy and toll plus experienced "
            "vehicle-dwell parking. This permits multimodal scoring during "
            "the JointReRoute cycle."
        ),
    )
    parser.add_argument(
        "--max-utility-selector",
        action="store_true",
        help=(
            "Before iteration 0, deterministically select the higher-utility "
            "existing bound or unbound household bundle. Bound routes must "
            "pass the passenger pickup and drop-off links."
        ),
    )
    parser.add_argument(
        "--endogenous-joint-candidates",
        action="store_true",
        help=(
            "Use the 384-leg household candidate registry, including 106 newly "
            "screened legs, and select bundles with household vehicle-resource conflicts."
        ),
    )
    return parser.parse_args()


def binding_row_count(path: Path, expected: int = EXPECTED_BINDING_ROWS) -> int:
    with path.open("r", encoding="utf-8") as handle:
        count = sum(1 for line in handle if line.strip()) - 1
    if count != expected:
        raise ValueError(
            f"Expected {expected} physical bindings; found {count}"
        )
    return count


def validate_template(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    set_car_distance_rate_zero(root)
    set_physical_transit_modes(root)
    set_pt_teleported_routing(root)
    set_taxi_scoring_contract(root)
    set_car_passenger_time_only(root)
    set_scoring_function_creation_after_replanning(root)
    freeze_canonical_plan_innovation(root)
    require_taxi_scoring_contract(root)
    require_car_passenger_time_only(root)
    require_physical_transit_modes(root)
    require_pt_teleported_routing(root)
    require_scoring_function_creation_after_replanning(root)
    require_canonical_plan_innovation_frozen(root)


def main() -> int:
    args = parse_args()
    if args.max_utility_selector and args.joint_reroute:
        raise ValueError("--max-utility-selector and --joint-reroute are mutually exclusive")
    if args.max_utility_selector and not args.dynamic_car_costs:
        raise ValueError("--max-utility-selector requires --dynamic-car-costs")
    if args.endogenous_joint_candidates and not args.max_utility_selector:
        raise ValueError("--endogenous-joint-candidates requires --max-utility-selector")
    base = safe_server_path(args.base_release, must_exist=True)
    template = safe_server_path(args.config_template, must_exist=True)
    payload = safe_server_path(args.payload_root, must_exist=True)
    release = safe_server_path(args.release_root, must_exist=False)
    run = safe_server_path(args.run_root, must_exist=False)
    if release.exists() or run.exists():
        raise FileExistsError("Release and run roots must both be absent")

    java = base / "runtime/jdk-25/bin/java"
    payload_jar = payload / "matsim-example-project-0.0.1-SNAPSHOT.jar"
    bindings_name = (
        "household_joint_candidate_bindings.csv"
        if args.endogenous_joint_candidates
        else "school_escort_physical_bindings.csv"
    )
    payload_bindings = payload / bindings_name
    payload_parking_zone_repairs = payload / "facility_tcs_zone_repairs.csv"
    require_regular(java, executable=True)
    require_regular(template)
    require_regular(payload_jar)
    require_regular(payload_bindings)
    if args.dynamic_car_costs:
        require_regular(payload_parking_zone_repairs)
    expected_binding_rows = (
        EXPECTED_ENDOGENOUS_BINDING_ROWS
        if args.endogenous_joint_candidates else EXPECTED_BINDING_ROWS
    )
    binding_rows = binding_row_count(payload_bindings, expected_binding_rows)
    for file_name in set(BASE_INPUT_PATHS.values()) | {
        "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz"
    }:
        require_regular(base / "input" / file_name)
    for directory in ("runtime", "input", "data/transport_costs/hongkong"):
        if not (base / directory).is_dir():
            raise ValueError(f"Base release directory is missing: {base / directory}")
    validate_template(template)

    release.mkdir()
    shutil.copytree(base / "runtime", release / "runtime", symlinks=True)
    shutil.copytree(base / "input", release / "input", symlinks=True)
    shutil.copytree(
        base / "data/transport_costs/hongkong",
        release / "data/transport_costs/hongkong",
    )
    if args.dynamic_car_costs:
        repair_dir = (
            release
            / "data/transport_costs/hongkong/car_cost_v1/dynamic_runtime_v1"
        )
        repair_dir.mkdir(exist_ok=True)
        shutil.copy2(
            payload_parking_zone_repairs,
            repair_dir / "facility_tcs_zone_repairs.csv",
        )
    (release / "app").mkdir()
    shutil.copy2(payload_jar, release / "app" / payload_jar.name)
    bindings = release / f"input/{bindings_name}"
    shutil.copy2(payload_bindings, bindings)
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    run.mkdir()
    config = run / (
        "config_stage11_school_escort_max_utility_1iteration.xml"
        if args.max_utility_selector
        else (
            "config_stage11_school_escort_joint_reroute_1cycle.xml"
            if args.joint_reroute
            else "config_stage11_school_escort_physical_1iteration.xml"
        )
    )
    plans_name = "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz"
    last_iteration = 1 if args.joint_reroute else 0
    write_run_config(template, config, release, run, last_iteration, plans_name)

    java = release / "runtime/jdk-25/bin/java"
    jar = release / "app/matsim-example-project-0.0.1-SNAPSHOT.jar"
    pt_root = release / "data/transport_costs/hongkong/pt_fare_v1"
    car_root = release / "data/transport_costs/hongkong/car_cost_v1"
    command = [
        str(java),
        f"-Xms{args.xms}",
        f"-Xmx{args.xmx}",
        "-cp",
        str(jar),
        "org.matsim.project.RunHongKong5Pct",
        str(config),
        "unused",
        "--simulate",
        f"--household-escort-bindings={bindings}",
    ]
    if args.joint_reroute:
        command.append("--household-escort-joint-reroute")
    if args.max_utility_selector:
        command.append("--household-escort-max-utility")
    if not args.joint_reroute or args.dynamic_car_costs:
        command.extend([
            "--multimodal-costs",
            f"--pt-fare-root={pt_root}",
            f"--car-cost-root={car_root}",
        ])
    if args.dynamic_car_costs:
        command.append("--dynamic-car-costs")
    worker = run / "worker.sh"
    worker.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"cd {shlex.quote(str(run))}\n"
        f"export HOME={shlex.quote(str(release / 'home'))}\n"
        f"export TMPDIR={shlex.quote(str(release / 'tmp'))}\n"
        f"export XDG_CACHE_HOME={shlex.quote(str(release / 'home/.cache'))}\n"
        f"/usr/bin/time -v {shell_join(command)}\n"
        "rc=$?\n"
        "printf '%s\\n' \"$rc\" > exit_code.txt\n"
        "date --iso-8601=seconds > finished_at.txt\n"
        "exit \"$rc\"\n",
        encoding="utf-8",
        newline="\n",
    )
    worker.chmod(worker.stat().st_mode | stat.S_IXUSR)
    metadata = {
        "objective": (
            "Fixed 139-pair school_escort physical QVehicle pilot with one "
            "binding-preserving JointReRoute cycle"
            if args.joint_reroute
            else (
                "Stage 11 endogenous household joint-candidate pilot with "
                "physical bound rides and real PT/Taxi/Walk release choices"
                if args.endogenous_joint_candidates
                else "Stage 11 household maximum-utility pilot with physical bound "
                "rides and real PT/Taxi/Walk choices for released passengers"
                if args.max_utility_selector
                else "Stage 11 fixed 139-pair school_escort physical QVehicle pilot"
            )
        ),
        "base_release": str(base),
        "config_template": str(template),
        "release_root": str(release),
        "run_root": str(run),
        "iterations_executed": list(range(last_iteration + 1)),
        "last_iteration": last_iteration,
        "joint_reroute": {
            "enabled": args.joint_reroute,
            "applications": 1 if args.joint_reroute else 0,
            "source_iteration": 0 if args.joint_reroute else None,
            "validation_iteration": 1 if args.joint_reroute else None,
            "fixed_binding_preserved": True,
        },
        "multimodal_costs": {
            "enabled": not args.joint_reroute or args.dynamic_car_costs,
            "dynamic_car_costs": args.dynamic_car_costs,
            "reason_when_disabled": (
                "Existing Car energy/toll/parking tables cover only the fixed "
                "canonical routes and cannot price rerouted driver legs."
                if args.joint_reroute and not args.dynamic_car_costs else None
            ),
        },
        "binding_rows": binding_rows,
        "binding_people": 244 if args.endogenous_joint_candidates else 139,
        "innovation": {
            "ChangeExpBeta": 1.0,
            "ReRoute": 0.0,
            "SubtourModeChoice": 0.0,
            "TimeAllocationMutator": 0.0,
        },
        "unbound_car_passenger_legs_remain_teleported": (
            None if args.endogenous_joint_candidates else 2456
        ),
        "household_max_utility_selector": {
            "enabled": args.max_utility_selector,
            "alternatives_per_candidate": 2 if args.max_utility_selector else None,
            "candidate_unit": (
                "single_passenger_leg"
                if args.endogenous_joint_candidates
                else "passenger_round_trip_bundle"
            ),
            "probabilistic_choice": False,
            "driver_participation_constraint": False,
            "new_joint_pair_generation": args.endogenous_joint_candidates,
            "endogenous_candidate_generation": args.endogenous_joint_candidates,
            "candidate_registry_legs": binding_rows,
            "candidate_registry_bundles": (
                384 if args.endogenous_joint_candidates else 139
            ),
            "candidate_registry_households": (
                240 if args.endogenous_joint_candidates else 139
            ),
            "new_candidate_legs": 106 if args.endogenous_joint_candidates else 0,
            "new_candidate_bundles": 106 if args.endogenous_joint_candidates else 0,
            "bound_candidate_requires_real_waypoints": args.max_utility_selector,
            "unbound_candidate_modes": (
                ["pt", "taxi", "walk"] if args.max_utility_selector else None
            ),
            "unbound_car_candidate_enabled": False,
            "car_availability_rule": (
                "No passenger Car candidate while the bound driver retains the household Car; "
                "future Car requires driver mode release or an explicitly unused additional vehicle."
                if args.max_utility_selector else None
            ),
        },
        "command": command,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    (run / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log_handle = (run / "run_stdout_stderr.log").open("x", encoding="utf-8")
    process = subprocess.Popen(
        [str(worker)],
        cwd=run,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    (run / "launcher_pid.txt").write_text(f"{process.pid}\n", encoding="ascii")
    print(json.dumps({"status": "STARTED", "pid": process.pid, **metadata}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"School-escort physical pilot launch failed: {error}", file=sys.stderr)
        raise
