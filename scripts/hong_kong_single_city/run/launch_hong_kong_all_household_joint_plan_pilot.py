#!/usr/bin/env python3
"""Launch the delayed all-car-household joint-plan Stage 11 pilot."""

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

from launch_hong_kong_stage11_direct_10it import (
    BASE_INPUT_PATHS,
    freeze_canonical_plan_innovation,
    require_canonical_plan_innovation_frozen,
    require_car_passenger_time_only,
    require_physical_transit_modes,
    require_pt_teleported_routing,
    require_regular,
    require_scoring_function_creation_after_replanning,
    require_taxi_scoring_contract,
    safe_server_path,
    set_car_distance_rate_zero,
    set_car_passenger_time_only,
    set_physical_transit_modes,
    set_pt_teleported_routing,
    set_scoring_function_creation_after_replanning,
    set_taxi_scoring_contract,
    shell_join,
    write_run_config,
)


EXPECTED_CANDIDATE_ROWS = 9_289
HOUSEHOLD_SELECTION_STRATEGY = "KeepLastSelected"


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


def row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        rows = sum(1 for line in handle if line.strip()) - 1
    if rows != EXPECTED_CANDIDATE_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_CANDIDATE_ROWS} household candidate rows; found {rows}"
        )
    return rows


def validate_template(path: Path) -> None:
    root = ET.parse(path).getroot()
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


def set_household_selection_only(root: ET.Element) -> None:
    """Preserve the plans chosen by the deterministic household selector."""
    replanning = next(
        module for module in root.findall("./module")
        if module.get("name") == "replanning"
    )
    changed = 0
    observed: dict[str, list[float]] = {}
    for settings in replanning.findall("./parameterset"):
        if settings.get("type") != "strategysettings":
            continue
        params = {param.get("name"): param for param in settings.findall("./param")}
        strategy = params["strategyName"].get("value")
        if strategy == "ChangeExpBeta":
            params["strategyName"].set("value", HOUSEHOLD_SELECTION_STRATEGY)
            strategy = HOUSEHOLD_SELECTION_STRATEGY
            changed += 1
        observed.setdefault(strategy, []).append(float(params["weight"].get("value")))
    if changed == 0:
        raise ValueError("No ChangeExpBeta strategy was available for household selection freeze")
    expected = {
        HOUSEHOLD_SELECTION_STRATEGY: [1.0, 1.0, 1.0],
        "ReRoute": [0.0, 0.0, 0.0],
        "SubtourModeChoice": [0.0, 0.0, 0.0],
        "TimeAllocationMutator": [0.0, 0.0, 0.0],
    }
    actual = {name: sorted(weights) for name, weights in observed.items()}
    if actual != expected:
        raise ValueError(f"Unexpected household replanning contract: {actual}")


def rewrite_household_run_config(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    set_household_selection_only(root)
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

    payload_jar = payload / "matsim-example-project-0.0.1-SNAPSHOT.jar"
    payload_candidates = payload / "household_joint_plan_potential_candidates.csv"
    payload_parking_repairs = payload / "facility_tcs_zone_repairs_with_driver_switch.csv"
    require_regular(base / "runtime/jdk-25/bin/java", executable=True)
    require_regular(template)
    require_regular(payload_jar)
    require_regular(payload_candidates)
    require_regular(payload_parking_repairs)
    candidate_rows = row_count(payload_candidates)
    for file_name in set(BASE_INPUT_PATHS.values()) | {
        "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz"
    }:
        require_regular(base / "input" / file_name)
    validate_template(template)

    release.mkdir()
    shutil.copytree(base / "runtime", release / "runtime", symlinks=True)
    shutil.copytree(base / "input", release / "input", symlinks=True)
    shutil.copytree(
        base / "data/transport_costs/hongkong",
        release / "data/transport_costs/hongkong",
    )
    repair_dir = release / "data/transport_costs/hongkong/car_cost_v1/dynamic_runtime_v1"
    repair_dir.mkdir(exist_ok=True)
    shutil.copy2(payload_parking_repairs, repair_dir / "facility_tcs_zone_repairs.csv")
    (release / "app").mkdir()
    shutil.copy2(payload_jar, release / "app" / payload_jar.name)
    candidates = release / "input/household_joint_plan_potential_candidates.csv"
    shutil.copy2(payload_candidates, candidates)
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    run.mkdir()
    config = run / "config_stage11_all_household_joint_plan_it0_it1.xml"
    write_run_config(
        template,
        config,
        release,
        run,
        1,
        "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz",
    )
    rewrite_household_run_config(config)

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
        "--multimodal-costs",
        "--dynamic-car-costs",
        f"--pt-fare-root={release / 'data/transport_costs/hongkong/pt_fare_v1'}",
        f"--car-cost-root={release / 'data/transport_costs/hongkong/car_cost_v1'}",
        f"--household-joint-plan-candidates={candidates}",
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
        "objective": (
            "Stage 11 all-car-household delayed joint-plan selection with real "
            "waypoints and car_passenger release to PT, Taxi, or Walk"
        ),
        "base_release": str(base),
        "config_template": str(template),
        "release_root": str(release),
        "run_root": str(run),
        "iterations_executed": [0, 1],
        "selection_after_iteration": 0,
        "physical_validation_iteration": 1,
        "candidate_rows": candidate_rows,
        "candidate_households": 5_789,
        "initial_physical_bindings": 0,
        "original_car_passenger_trips": 2_734,
        "car_passenger_release_modes": ["pt", "taxi", "walk"],
        "school_bus_candidate_generation": False,
        "driver_switch_rule": "complete home-based day converted to Car",
        "passenger_trip_unit": "single main trip; directions independent",
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
        print(f"All-household joint-plan launch failed: {error}", file=sys.stderr)
        raise
