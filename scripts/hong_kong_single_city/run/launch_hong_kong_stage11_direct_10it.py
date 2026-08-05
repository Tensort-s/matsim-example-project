#!/usr/bin/env python3
"""Prepare one lean Stage 11 release and launch one 10-iteration run.

This direct runner intentionally validates operational dependencies by path,
format, and successful loading rather than by duplicating SHA registries.  It
never overwrites an existing staging, release, run, or output directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET


SERVER_ROOT = Path("/mnt/DiskM/by")
TAXI_MODE_PARAMS = {
    "constant": "-9",
    "marginalUtilityOfTraveling_util_hr": "-6",
    "marginalUtilityOfDistance_util_m": "0",
    "monetaryDistanceRate": "0",
    "dailyMonetaryConstant": "0",
    "dailyUtilityConstant": "0",
}
SCORING_FUNCTION_CREATION_EVENT = "BeforeMobsim"
SCORING_FUNCTION_CREATION_PARAM = "createScoringFunctionType"
FROZEN_INNOVATION_STRATEGIES = {
    "ReRoute",
    "SubtourModeChoice",
    "TimeAllocationMutator",
}
INPUT_PATHS = {
    ("network", "inputNetworkFile"): "network.xml.gz",
    ("plans", "inputPlansFile"): "plans_routed_5pct_v2.xml.gz",
    ("facilities", "inputFacilitiesFile"): "facilities_5pct_v2.xml.gz",
    ("vehicles", "vehiclesFile"): "privateVehicles_5pct.xml.gz",
    ("transit", "transitScheduleFile"): "transitSchedule_5pct.xml.gz",
    ("transit", "vehiclesFile"): "transitVehicles_10pct.xml.gz",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-release", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--last-iteration", type=int, default=10)
    parser.add_argument("--xms", default="16g")
    parser.add_argument("--xmx", default="96g")
    return parser.parse_args()


def safe_server_path(path: Path, *, must_exist: bool) -> Path:
    resolved = path.resolve(strict=must_exist)
    if resolved == SERVER_ROOT or SERVER_ROOT not in resolved.parents:
        raise ValueError(f"Path must be a child of {SERVER_ROOT}: {resolved}")
    return resolved


def require_regular(path: Path, *, executable: bool = False) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required regular file is missing: {path}")
    if executable and not os.access(path, os.X_OK):
        raise ValueError(f"Required executable is not executable: {path}")


def unique_module(root: ET.Element, name: str) -> ET.Element:
    matches = [item for item in root.findall("./module") if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one module {name!r}; found {len(matches)}")
    return matches[0]


def unique_param(module: ET.Element, name: str) -> ET.Element:
    matches = [item for item in module.findall("./param") if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one parameter {module.get('name')}.{name}; "
            f"found {len(matches)}"
        )
    return matches[0]


def set_car_distance_rate_zero(root: ET.Element) -> None:
    scoring = unique_module(root, "scoring")
    car_sets = []
    for parameter_set in scoring.findall("./parameterset"):
        if parameter_set.get("type") != "modeParams":
            continue
        modes = [
            item
            for item in parameter_set.findall("./param")
            if item.get("name") == "mode" and item.get("value") == "car"
        ]
        if modes:
            car_sets.append(parameter_set)
    if len(car_sets) != 1:
        raise ValueError(f"Expected exactly one Car modeParams set; found {len(car_sets)}")
    distance_rate = unique_param(car_sets[0], "monetaryDistanceRate")
    if distance_rate.get("value") != "-0.0007":
        raise ValueError(
            "Expected the authorized source Car monetaryDistanceRate -0.0007; "
            f"found {distance_rate.get('value')!r}"
        )
    distance_rate.set("value", "0")


def taxi_mode_sets(root: ET.Element) -> tuple[ET.Element, list[ET.Element]]:
    scoring = unique_module(root, "scoring")
    matches = []
    for parameter_set in scoring.findall("./parameterset"):
        if parameter_set.get("type") != "modeParams":
            continue
        modes = [
            item
            for item in parameter_set.findall("./param")
            if item.get("name") == "mode" and item.get("value") == "taxi"
        ]
        if modes:
            matches.append(parameter_set)
    return scoring, matches


def set_taxi_scoring_contract(root: ET.Element) -> None:
    """Write the user-authorized Taxi leg formula into the derived config."""
    scoring, matches = taxi_mode_sets(root)
    if len(matches) > 1:
        raise ValueError(
            "Joint Taxi/PT/Car scoring permits at most one Taxi modeParams set; "
            f"found {len(matches)}"
        )
    if matches:
        taxi = matches[0]
    else:
        taxi = ET.SubElement(scoring, "parameterset", {"type": "modeParams"})
        ET.SubElement(taxi, "param", {"name": "mode", "value": "taxi"})
    for name, value in TAXI_MODE_PARAMS.items():
        parameters = [item for item in taxi.findall("./param") if item.get("name") == name]
        if len(parameters) > 1:
            raise ValueError(f"Duplicate Taxi scoring parameter: {name}")
        if parameters:
            parameters[0].set("value", value)
        else:
            ET.SubElement(taxi, "param", {"name": name, "value": value})


def require_taxi_scoring_contract(root: ET.Element) -> None:
    """Verify the exact authorized Taxi scoring parameters after derivation."""
    _, matches = taxi_mode_sets(root)
    if len(matches) != 1:
        raise ValueError(
            "Joint Taxi/PT/Car scoring requires exactly one Taxi modeParams set; "
            f"found {len(matches)}"
        )
    taxi = matches[0]
    for name, expected in TAXI_MODE_PARAMS.items():
        actual = unique_param(taxi, name).get("value")
        if float(actual if actual is not None else "nan") != float(expected):
            raise ValueError(
                f"Taxi {name} must be {expected}; found {actual!r}"
            )


def set_scoring_function_creation_after_replanning(root: ET.Element) -> None:
    """Snapshot selected-plan cost schedules after replanning, before QSim."""
    controller = unique_module(root, "controller")
    matches = [
        item
        for item in controller.findall("./param")
        if item.get("name") == SCORING_FUNCTION_CREATION_PARAM
    ]
    if len(matches) > 1:
        raise ValueError(
            f"Duplicate controller.{SCORING_FUNCTION_CREATION_PARAM} parameters"
        )
    if matches:
        matches[0].set("value", SCORING_FUNCTION_CREATION_EVENT)
    else:
        ET.SubElement(
            controller,
            "param",
            {
                "name": SCORING_FUNCTION_CREATION_PARAM,
                "value": SCORING_FUNCTION_CREATION_EVENT,
            },
        )


def require_scoring_function_creation_after_replanning(root: ET.Element) -> None:
    controller = unique_module(root, "controller")
    actual = unique_param(
        controller, SCORING_FUNCTION_CREATION_PARAM
    ).get("value")
    if actual != SCORING_FUNCTION_CREATION_EVENT:
        raise ValueError(
            f"controller.{SCORING_FUNCTION_CREATION_PARAM} must be "
            f"{SCORING_FUNCTION_CREATION_EVENT}; found {actual!r}"
        )


def freeze_canonical_plan_innovation(root: ET.Element) -> None:
    """Keep Stage 11 on plans covered by the static canonical cost tables."""
    replanning = unique_module(root, "replanning")
    counts: dict[tuple[str, str], int] = {}
    for settings in replanning.findall("./parameterset"):
        if settings.get("type") != "strategysettings":
            continue
        strategy = unique_param(settings, "strategyName").get("value")
        subpopulation = unique_param(settings, "subpopulation").get("value")
        if strategy is None or subpopulation is None:
            raise ValueError("Replanning strategy and subpopulation must be explicit")
        key = (subpopulation, strategy)
        counts[key] = counts.get(key, 0) + 1
        weight = unique_param(settings, "weight")
        if strategy == "ChangeExpBeta":
            weight.set("value", "1")
        elif strategy in FROZEN_INNOVATION_STRATEGIES:
            weight.set("value", "0")
        else:
            raise ValueError(f"Unexpected Stage 11 replanning strategy: {strategy}")
    subpopulations = {subpopulation for subpopulation, _ in counts}
    if not subpopulations:
        raise ValueError("No Stage 11 replanning subpopulations found")
    expected = {"ChangeExpBeta", *FROZEN_INNOVATION_STRATEGIES}
    for subpopulation in subpopulations:
        actual = {
            strategy
            for candidate_subpopulation, strategy in counts
            if candidate_subpopulation == subpopulation
        }
        if actual != expected or any(
            counts[(subpopulation, strategy)] != 1 for strategy in expected
        ):
            raise ValueError(
                f"Unexpected replanning strategy contract for {subpopulation}: "
                f"{sorted(actual)}"
            )


def require_canonical_plan_innovation_frozen(root: ET.Element) -> None:
    replanning = unique_module(root, "replanning")
    observed = 0
    for settings in replanning.findall("./parameterset"):
        if settings.get("type") != "strategysettings":
            continue
        strategy = unique_param(settings, "strategyName").get("value")
        weight = unique_param(settings, "weight").get("value")
        expected = "1" if strategy == "ChangeExpBeta" else "0"
        if strategy not in {"ChangeExpBeta", *FROZEN_INNOVATION_STRATEGIES}:
            raise ValueError(f"Unexpected Stage 11 replanning strategy: {strategy}")
        if float(weight if weight is not None else "nan") != float(expected):
            raise ValueError(
                f"Stage 11 strategy {strategy} must have weight {expected}; "
                f"found {weight!r}"
            )
        observed += 1
    if observed == 0:
        raise ValueError("No Stage 11 replanning strategies were verified")


def write_run_config(template: Path, destination: Path, release: Path, run: Path,
                     last_iteration: int) -> None:
    tree = ET.parse(template)
    root = tree.getroot()
    for (module_name, param_name), file_name in INPUT_PATHS.items():
        unique_param(unique_module(root, module_name), param_name).set(
            "value", str(release / "input" / file_name)
        )
    controller = unique_module(root, "controller")
    updates = {
        "firstIteration": "0",
        "lastIteration": str(last_iteration),
        "outputDirectory": str(run / "output"),
        "overwriteFiles": "failIfDirectoryExists",
        "writeEventsInterval": "1",
        "writePlansInterval": "1",
        "writeSnapshotsInterval": "0",
    }
    for name, value in updates.items():
        unique_param(controller, name).set("value", value)
    set_car_distance_rate_zero(root)
    set_taxi_scoring_contract(root)
    set_scoring_function_creation_after_replanning(root)
    freeze_canonical_plan_innovation(root)
    require_taxi_scoring_contract(root)
    require_scoring_function_creation_after_replanning(root)
    require_canonical_plan_innovation_frozen(root)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(
            '<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        )
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")
    ET.parse(destination)


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(item) for item in parts)


def main() -> int:
    args = parse_args()
    if args.last_iteration != 10:
        raise ValueError("This Stage 11 direct runner permits exactly lastIteration=10")
    base = safe_server_path(args.base_release, must_exist=True)
    payload = safe_server_path(args.payload_root, must_exist=True)
    release = safe_server_path(args.release_root, must_exist=False)
    run = safe_server_path(args.run_root, must_exist=False)
    if release.exists() or run.exists():
        raise FileExistsError("Release and run roots must both be absent")

    base_java = base / "runtime/jdk-25/bin/java"
    template = base / "config/config_formal_50it.xml"
    payload_jar = payload / "matsim-example-project-0.0.1-SNAPSHOT.jar"
    pt_payload = payload / "pt_fare_v1"
    car_payload = payload / "car_cost_v1"
    require_regular(base_java, executable=True)
    require_regular(template)
    require_regular(payload_jar)
    if not pt_payload.is_dir() or not car_payload.is_dir():
        raise ValueError("Payload must contain pt_fare_v1 and car_cost_v1 directories")
    for file_name in INPUT_PATHS.values():
        require_regular(base / "input" / file_name)

    # The semantic scoring contract is checked before allocating either of
    # the two immutable target directories. Operational input identity is not
    # delegated to a second SHA registry.
    source_tree = ET.parse(template)
    set_car_distance_rate_zero(source_tree.getroot())
    set_taxi_scoring_contract(source_tree.getroot())
    set_scoring_function_creation_after_replanning(source_tree.getroot())
    freeze_canonical_plan_innovation(source_tree.getroot())
    require_taxi_scoring_contract(source_tree.getroot())
    require_scoring_function_creation_after_replanning(source_tree.getroot())
    require_canonical_plan_innovation_frozen(source_tree.getroot())

    release.mkdir()
    shutil.copytree(base / "runtime", release / "runtime", symlinks=True)
    shutil.copytree(base / "input", release / "input", symlinks=True)
    (release / "app").mkdir()
    shutil.copy2(payload_jar, release / "app" / payload_jar.name)
    cost_root = release / "data/transport_costs/hongkong"
    cost_root.mkdir(parents=True)
    shutil.copytree(pt_payload, cost_root / "pt_fare_v1")
    shutil.copytree(car_payload, cost_root / "car_cost_v1")
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    run.mkdir()
    config = run / "config_stage11_direct_10it.xml"
    write_run_config(template, config, release, run, args.last_iteration)

    java = release / "runtime/jdk-25/bin/java"
    jar = release / "app/matsim-example-project-0.0.1-SNAPSHOT.jar"
    pt_root = cost_root / "pt_fare_v1"
    car_root = cost_root / "car_cost_v1"
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
        "--multimodal-costs",
        f"--pt-fare-root={pt_root}",
        f"--car-cost-root={car_root}",
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
    started_at = datetime.now(timezone.utc).astimezone().isoformat()
    metadata = {
        "objective": "One Hong Kong Stage 11 Taxi/PT/Car joint 10-iteration run",
        "base_release": str(base),
        "release_root": str(release),
        "run_root": str(run),
        "last_iteration": args.last_iteration,
        "authorized_config_change": {"car monetaryDistanceRate": {"from": -0.0007, "to": 0}},
        "authorized_taxi_leg_score": {
            "formula": "-9 - 6 * travel_time_hours - 0.05 * route_based_fare_hkd",
            "mode_params": TAXI_MODE_PARAMS,
            "fare_utility_per_hkd": 0.05,
            "fare_share_factor": 1.0,
        },
        "joint_scoring": True,
        "scoring_function_creation_event": SCORING_FUNCTION_CREATION_EVENT,
        "canonical_plan_innovation": {
            "ChangeExpBeta": 1.0,
            "ReRoute": 0.0,
            "SubtourModeChoice": 0.0,
            "TimeAllocationMutator": 0.0,
        },
        "pt_fare_root": str(pt_root),
        "car_cost_root": str(car_root),
        "command": command,
        "started_at": started_at,
    }
    (run / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
        print(f"Stage 11 direct launch failed: {error}", file=sys.stderr)
        raise
