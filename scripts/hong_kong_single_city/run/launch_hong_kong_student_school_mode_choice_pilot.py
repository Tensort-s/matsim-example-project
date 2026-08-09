#!/usr/bin/env python3
"""Launch one Stage 11 iteration-0/1 student school-mode choice pilot.

The run compares physical school bus, regular PT, Taxi, Walk, and eligible
household car-passenger candidates by deterministic maximum utility. School-bus
seat capacity is deliberately disabled by the Java runner. The physical
non-Taxi mechanical gate also disables ordinary-PT seat competition at runtime;
the adopted 10% vehicle file is copied unchanged.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

from launch_hong_kong_all_household_joint_plan_pilot import (
    rewrite_household_run_config,
)
from launch_hong_kong_stage11_direct_10it import (
    require_regular,
    safe_server_path,
    scoring_mode_sets,
    shell_join,
    unique_module,
    unique_param,
    write_run_config,
)


SCHOOL_BUS_MODE = "school_bus"
PHYSICAL_TRANSIT_MODES = "pt,bus,gmb,train,light_rail,ferry,school_bus"
SCHOOL_BUS_SCORING = {
    "constant": "-1.5",
    "marginalUtilityOfTraveling_util_hr": "-6",
    "marginalUtilityOfDistance_util_m": "0",
    "monetaryDistanceRate": "0",
    "dailyMonetaryConstant": "0",
    "dailyUtilityConstant": "0",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-release", type=Path, required=True)
    parser.add_argument("--config-template", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--xms", default="16g")
    parser.add_argument("--xmx", default="96g")
    return parser.parse_args()


def csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig") as handle:
        return max(0, sum(1 for line in handle if line.strip()) - 1)


def configure_physical_school_bus(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    unique_param(unique_module(root, "transit"), "transitModes").set(
        "value", PHYSICAL_TRANSIT_MODES
    )
    routing = unique_module(root, "routing")
    for block in list(routing.findall("./parameterset")):
        if block.get("type") != "teleportedModeParameters":
            continue
        modes = [
            item.get("value")
            for item in block.findall("./param")
            if item.get("name") == "mode"
        ]
        if modes == [SCHOOL_BUS_MODE]:
            routing.remove(block)
    _, mode_sets = scoring_mode_sets(root, SCHOOL_BUS_MODE)
    if len(mode_sets) != 1:
        raise ValueError(
            f"Expected one school_bus scoring block; found {len(mode_sets)}"
        )
    for name, value in SCHOOL_BUS_SCORING.items():
        matches = [
            item for item in mode_sets[0].findall("./param")
            if item.get("name") == name
        ]
        if len(matches) > 1:
            raise ValueError(f"Duplicate school_bus scoring parameter {name}")
        if matches:
            matches[0].set("value", value)
        else:
            ET.SubElement(
                mode_sets[0], "param", {"name": name, "value": value}
            )
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(
            '<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        )
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")
    ET.parse(path)


def main() -> int:
    args = parse_args()
    base = safe_server_path(args.base_release, must_exist=True)
    template = safe_server_path(args.config_template, must_exist=True)
    payload = safe_server_path(args.payload_root, must_exist=True)
    release = safe_server_path(args.release_root, must_exist=False)
    run = safe_server_path(args.run_root, must_exist=False)
    if release.exists() or run.exists():
        raise FileExistsError("Release and run roots must both be new directories")

    jar = payload / "matsim-example-project-0.0.1-SNAPSHOT.jar"
    supply = payload / "school_bus_supply_v6"
    student_candidates = payload / "school_bus_plan_candidates_5pct_v6"
    household_candidates_name = "household_joint_plan_potential_candidates.csv"
    household_candidates = base / "input" / household_candidates_name
    payload_files = {
        supply / "network.xml.gz": "network.xml.gz",
        supply / "transitSchedule_5pct_school_bus_v6.xml.gz": "transitSchedule_5pct.xml.gz",
        supply / "transitVehicles_10pct_regular_school_bus_unscaled.xml.gz": "transitVehicles_10pct.xml.gz",
    }
    require_regular(base / "runtime/jdk-25/bin/java", executable=True)
    require_regular(template)
    require_regular(jar)
    require_regular(household_candidates)
    for source in payload_files:
        require_regular(source)
    for name in ("school_trip_universe_v6.csv", "school_bus_physical_route_candidates_v6.csv"):
        require_regular(student_candidates / name)

    release.mkdir()
    shutil.copytree(base / "runtime", release / "runtime", symlinks=True)
    shutil.copytree(base / "input", release / "input", symlinks=True)
    shutil.copytree(
        base / "data/transport_costs/hongkong",
        release / "data/transport_costs/hongkong",
    )
    for source, destination in payload_files.items():
        shutil.copy2(source, release / "input" / destination)
    release_candidates = release / "input/school_bus_plan_candidates_5pct_v6"
    shutil.copytree(student_candidates, release_candidates)
    (release / "app").mkdir()
    shutil.copy2(jar, release / "app" / jar.name)
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    run.mkdir()
    config = run / "config_stage11_student_school_mode_it0_it1.xml"
    write_run_config(
        template,
        config,
        release,
        run,
        1,
        "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz",
    )
    rewrite_household_run_config(config)
    configure_physical_school_bus(config)

    command = [
        str(release / "runtime/jdk-25/bin/java"),
        f"-Xms{args.xms}",
        f"-Xmx{args.xmx}",
        "-cp",
        str(release / "app/matsim-example-project-0.0.1-SNAPSHOT.jar"),
        "org.matsim.project.RunHongKong5Pct",
        str(config),
        "unused",
        "--simulate",
        "--clear-pt-routes",
        "--multimodal-costs",
        "--dynamic-car-costs",
        f"--pt-fare-root={release / 'data/transport_costs/hongkong/pt_fare_v1'}",
        f"--car-cost-root={release / 'data/transport_costs/hongkong/car_cost_v1'}",
        f"--household-joint-plan-candidates={release / 'input' / household_candidates_name}",
        f"--student-school-mode-candidates={release_candidates}",
        "--physical-nontaxi-modes",
        "--unlimited-ordinary-pt-capacity",
    ]
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
        "objective": "Stage 11 no-innovation integrated physical Car/PT/Walk/school-bus/car-passenger validation",
        "base_release": str(base),
        "release_root": str(release),
        "run_root": str(run),
        "iterations_executed": [0, 1],
        "selection_after_iteration": 0,
        "physical_validation_iteration": 1,
        "student_school_trip_rows": csv_rows(
            student_candidates / "school_trip_universe_v6.csv"
        ),
        "physical_school_bus_candidate_rows": csv_rows(
            student_candidates / "school_bus_physical_route_candidates_v6.csv"
        ),
        "independent_modes": ["pt", "taxi", "walk", "school_bus"],
        "household_joint_mode": "car_passenger",
        "choice_rule": "deterministic maximum utility",
        "school_bus_capacity_constraint": False,
        "school_bus_runtime_seats_per_vehicle_type": 1_000_000,
        "physical_execution": {
            "car": "QNetwork with dynamic energy/toll/parking scoring",
            "car_passenger": "household driver binding when selected",
            "pt": "TransitQSim stop/vehicle boarding and alighting",
            "school_bus": "TransitQSim with guarded school-bus candidate/vehicle",
            "walk": "capacity-free NetworkRoute link traversal at 1.34 m/s",
            "taxi": "teleported (sole teleported main mode)",
        },
        "ordinary_pt_capacity_constraint": False,
        "ordinary_pt_capacity_note": (
            "technical physical-execution gate only; adopted 10% supply files are unchanged"
        ),
        "school_bus_scoring": SCHOOL_BUS_SCORING,
        "ordinary_innovation": {
            "KeepLastSelected": 1.0,
            "ReRoute": 0.0,
            "SubtourModeChoice": 0.0,
            "TimeAllocationMutator": 0.0,
        },
        "command": command,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    (run / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log_handle = (run / "run_stdout_stderr.log").open("x", encoding="utf-8")
    process = subprocess.Popen(
        [str(worker)], cwd=run, stdout=log_handle,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    log_handle.close()
    (run / "launcher_pid.txt").write_text(f"{process.pid}\n", encoding="ascii")
    print(json.dumps({"status": "STARTED", "pid": process.pid, **metadata}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Student school-mode launch failed: {error}", file=sys.stderr)
        raise
