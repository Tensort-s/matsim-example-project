#!/usr/bin/env python3
"""Create an immutable Candidate11 release and launch exactly 20 QSim runs (0..19)."""

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
import xml.etree.ElementTree as ET


SERVER_ROOT = Path("/mnt/DiskM/by")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-input-release", type=Path, required=True)
    parser.add_argument("--previous-app-release", type=Path, required=True)
    parser.add_argument("--config-template", type=Path, required=True)
    parser.add_argument("--payload-jar", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--xms", default="16g")
    parser.add_argument("--xmx", default="128g")
    return parser.parse_args()


def safe(path: Path, *, exists: bool) -> Path:
    result = path.resolve(strict=exists)
    if result == SERVER_ROOT or SERVER_ROOT not in result.parents:
        raise ValueError(f"Path must be below {SERVER_ROOT}: {result}")
    return result


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


def derive_config(template: Path, destination: Path, run: Path) -> None:
    tree = ET.parse(template)
    root = tree.getroot()
    set_param(module(root, "global"), "numberOfThreads", "16")
    qsim = module(root, "qsim")
    set_param(qsim, "numberOfThreads", "16")
    # Preserve the adopted road-stuck audit threshold. The template used by the
    # first attempt still contained the historical 600 s value.
    set_param(qsim, "stuckTime", "3600")

    controller = module(root, "controller")
    updates = {
        "firstIteration": "0",
        # MATSim executes both endpoints: 0..19 is exactly 20 QSim executions.
        "lastIteration": "19",
        "outputDirectory": str(run / "output"),
        "overwriteFiles": "failIfDirectoryExists",
        "createGraphsInterval": "10",
        "legDurationsInterval": "10",
        "legHistogramInterval": "10",
        "writeTripsInterval": "10",
        "writeEventsInterval": "10",
        "writePlansInterval": "10",
        "writeSnapshotsInterval": "0",
        "createScoringFunctionType": "BeforeMobsim",
    }
    for name, value in updates.items():
        set_param(controller, name, value)
    set_param(module(root, "scoring"), "writeExperiencedPlans", "true")

    subtour = module(root, "subtourModeChoice")
    set_param(subtour, "modes", "car,pt,walk,taxi")
    set_param(subtour, "chainBasedModes", "car")

    destination.parent.mkdir(parents=True, exist_ok=False)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("<?xml version='1.0' encoding='utf-8'?>\n")
        handle.write('<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n')
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")
    ET.parse(destination)


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def main() -> int:
    args = parse_args()
    runtime = safe(args.runtime_input_release, exists=True)
    previous = safe(args.previous_app_release, exists=True)
    template = safe(args.config_template, exists=True)
    payload_jar = safe(args.payload_jar, exists=True)
    release = safe(args.release_root, exists=False)
    run = safe(args.run_root, exists=False)
    if release.exists() or run.exists():
        raise FileExistsError("Release and run roots must both be absent")
    for required in (
        runtime / "runtime/jdk-25/bin/java",
        runtime / "input/household_joint_plan_potential_candidates.csv",
        template,
        payload_jar,
    ):
        if not required.is_file() or required.is_symlink():
            raise ValueError(f"Required regular file is missing: {required}")
    pt_source = runtime / "data/transport_costs/hongkong/pt_fare_v1"
    car_source = previous / "data/transport_costs/hongkong/car_cost_v1"
    for required in (
        runtime / "input/school_bus_plan_candidates_5pct_v6",
        pt_source,
        car_source,
    ):
        if not required.is_dir() or required.is_symlink():
            raise ValueError(f"Required directory is missing: {required}")

    release.mkdir()
    (release / "app").mkdir()
    shutil.copy2(payload_jar, release / "app/matsim-example-project-0.0.1-SNAPSHOT.jar")
    cost_root = release / "data/transport_costs/hongkong"
    cost_root.mkdir(parents=True)
    # run13e deliberately used the complete adopted PT catalog from release11
    # and the dynamic Car tables from release16. Keep those proven sources
    # separate; release16's compact PT mirror is not a complete runtime input.
    shutil.copytree(pt_source, cost_root / "pt_fare_v1")
    shutil.copytree(car_source, cost_root / "car_cost_v1")
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    config = run / "config_candidate11_open_taxi_walk_20qsim.xml"
    derive_config(template, config, run)
    java = runtime / "runtime/jdk-25/bin/java"
    jar = release / "app/matsim-example-project-0.0.1-SNAPSHOT.jar"
    command = [
        str(java), f"-Xms{args.xms}", f"-Xmx{args.xmx}", "-cp", str(jar),
        "org.matsim.project.RunHongKong5Pct", str(config), "unused",
        "--simulate", "--clear-pt-routes", "--multimodal-costs", "--dynamic-car-costs",
        f"--pt-fare-root={cost_root / 'pt_fare_v1'}",
        f"--car-cost-root={cost_root / 'car_cost_v1'}",
        f"--household-joint-plan-candidates={runtime / 'input/household_joint_plan_potential_candidates.csv'}",
        f"--student-school-mode-candidates={runtime / 'input/school_bus_plan_candidates_5pct_v6'}",
        "--household-joint-plan-with-ordinary-innovation",
        "--physical-nontaxi-modes", "--unlimited-ordinary-pt-capacity",
        "--traffic-signals", "--all-person-network-taxi-innovation",
        "--walk-overtime-scoring",
    ]
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
        "objective": "Candidate11 open innovation with all-person road Taxi and Walk overtime",
        "qsim_iterations": list(range(20)),
        "global_threads": 16,
        "qsim_threads": 16,
        "stuck_time_s": 3600,
        "protected_selection_target_iterations": [5, 10, 15],
        "taxi_utility": {
            "adult": "-9 - 6*t_h - 0.10*fare_hkd",
            "student": "-9 - 6*t_h - 0.15*fare_hkd",
            "road_proxy": "PCU=1; no cruising, deadheading, or fleet matching",
        },
        "walk_overtime": "-3.278342*max(0, cumulative_main_trip_walk_h-1/6)",
        "runtime_input_release": str(runtime),
        "previous_app_release": str(previous),
        "pt_fare_source": str(pt_source),
        "car_cost_source": str(car_source),
        "release_root": str(release),
        "run_root": str(run),
        "command": command,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    (run / "run_metadata.json").write_text(
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
