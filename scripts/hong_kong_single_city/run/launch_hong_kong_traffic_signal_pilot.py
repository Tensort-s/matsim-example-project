#!/usr/bin/env python3
"""Launch a new no-innovation Stage 11 run with a validated signal pilot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import xml.etree.ElementTree as ET

from launch_hong_kong_all_household_joint_plan_pilot import (
    rewrite_household_run_config,
)
from launch_hong_kong_stage11_direct_10it import (
    require_regular,
    safe_server_path,
    shell_join,
    write_run_config,
)
from launch_hong_kong_student_school_mode_choice_pilot import (
    configure_physical_school_bus,
)


SIGNAL_FILENAMES = (
    "signal_systems.xml",
    "signal_groups.xml",
    "signal_control.xml",
    "amber_times.xml",
    "intergreen_times.xml",
)


def validate_all_expressed_binding(pilot_summary: dict, validation_summary: dict) -> None:
    active_junctions = pilot_summary.get(
        "active_junction_count", pilot_summary.get("junction_count")
    )
    expected = {
        "status": "pass",
        "selection_scope": "all_expressed",
        "junction_count": active_junctions,
        "public_diagram_junction_count": 8,
        "diagram_special_treatment_count": 0,
        "production_adopted": False,
    }
    mismatches = {
        key: {"expected": value, "actual": validation_summary.get(key)}
        for key, value in expected.items()
        if validation_summary.get(key) != value
    }
    if mismatches:
        raise ValueError(
            "All-expressed signal payload failed validation binding: "
            + json.dumps(mismatches, sort_keys=True)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-release", type=Path, required=True)
    parser.add_argument("--config-template", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--period", choices=("am", "pm", "tod"), required=True)
    parser.add_argument("--last-iteration", type=int, default=1)
    parser.add_argument("--stuck-time", type=int, default=600)
    parser.add_argument("--xms", default="16g")
    parser.add_argument("--xmx", default="96g")
    return parser.parse_args()


def write_config(path: Path, release: Path, run: Path, period: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    if any(module.get("name") == "signalsystems" for module in root.findall("./module")):
        raise ValueError("Config template already contains a signalsystems module")
    qsim_modules = [
        module for module in root.findall("./module") if module.get("name") == "qsim"
    ]
    if len(qsim_modules) != 1:
        raise ValueError(f"Expected exactly one qsim module; found {len(qsim_modules)}")
    fast_capacity = [
        item for item in qsim_modules[0].findall("./param")
        if item.get("name") == "usingFastCapacityUpdate"
    ]
    if len(fast_capacity) > 1:
        raise ValueError("Duplicate qsim.usingFastCapacityUpdate parameters")
    if fast_capacity:
        fast_capacity[0].set("value", "false")
    else:
        ET.SubElement(
            qsim_modules[0],
            "param",
            {"name": "usingFastCapacityUpdate", "value": "false"},
        )
    signals = ET.SubElement(root, "module", {"name": "signalsystems"})
    signal_directory = "traffic_signals_tod" if period == "tod" else f"traffic_signals_{period}"
    signal_root = release / "input" / signal_directory
    parameters = {
        "useSignalsystems": "true",
        "signalsystems": str(signal_root / "signal_systems.xml"),
        "signalgroups": str(signal_root / "signal_groups.xml"),
        "signalcontrol": str(signal_root / "signal_control.xml"),
        "useAmbertimes": "true",
        "ambertimes": str(signal_root / "amber_times.xml"),
        "useIntergreentimes": "true",
        "intergreentimes": str(signal_root / "intergreen_times.xml"),
        "intersectionLogic": "NONE",
        "actionOnIntergreenViolation": "EXCEPTION",
        "actionOnConflictingDirectionViolation": "EXCEPTION",
    }
    for name, value in parameters.items():
        ET.SubElement(signals, "param", {"name": name, "value": value})
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        stream.write('<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n')
        stream.write(ET.tostring(root, encoding="unicode"))
        stream.write("\n")
    ET.parse(path)


def set_qsim_stuck_time(path: Path, stuck_time_s: int) -> None:
    if stuck_time_s <= 0:
        raise ValueError("stuck time must be positive")
    tree = ET.parse(path)
    parameters = tree.findall("./module[@name='qsim']/param[@name='stuckTime']")
    if len(parameters) != 1:
        raise ValueError(
            f"Expected exactly one qsim.stuckTime parameter; found {len(parameters)}"
        )
    parameters[0].set("value", str(stuck_time_s))
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        stream.write('<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n')
        stream.write(ET.tostring(tree.getroot(), encoding="unicode"))
        stream.write("\n")
    ET.parse(path)


def main() -> int:
    args = parse_args()
    if args.last_iteration < 0:
        raise ValueError("last iteration must be non-negative")
    if args.stuck_time <= 0:
        raise ValueError("stuck time must be positive")
    base = safe_server_path(args.base_release, must_exist=True)
    template = safe_server_path(args.config_template, must_exist=True)
    payload = safe_server_path(args.payload_root, must_exist=True)
    release = safe_server_path(args.release_root, must_exist=False)
    run = safe_server_path(args.run_root, must_exist=False)
    if release.exists() or run.exists():
        raise FileExistsError("Release and run roots must both be new directories")

    jar = payload / "matsim-example-project-0.0.1-SNAPSHOT.jar"
    pilot = payload / "traffic_signal_pilot"
    pilot_network = pilot / "network_signal_capacity_deconvolved.xml.gz"
    pilot_signals = pilot / ("matsim" if args.period == "tod" else f"matsim_{args.period}")
    pilot_summary_file = pilot / "pilot_build_summary.json"
    validation_summary_file = pilot / "tod_validation_summary.json"
    require_regular(base / "runtime/jdk-25/bin/java", executable=True)
    require_regular(template)
    require_regular(jar)
    require_regular(pilot_network)
    require_regular(pilot_summary_file)
    for name in SIGNAL_FILENAMES:
        require_regular(pilot_signals / name)
    pilot_summary = json.loads(pilot_summary_file.read_text(encoding="utf-8"))
    pilot_version = pilot_summary.get("pilot_version", "pilot_v1_historical")
    active_junctions = pilot_summary.get(
        "active_junction_count", pilot_summary.get("junction_count")
    )
    validation_summary = None
    if pilot_version == "territory_wide_v3_tod_all_expressed_proxy":
        require_regular(validation_summary_file)
        validation_summary = json.loads(validation_summary_file.read_text(encoding="utf-8"))
        validate_all_expressed_binding(pilot_summary, validation_summary)

    release.mkdir()
    shutil.copytree(base / "runtime", release / "runtime", symlinks=True)
    shutil.copytree(base / "input", release / "input", symlinks=True)
    shutil.copytree(
        base / "data/transport_costs/hongkong",
        release / "data/transport_costs/hongkong",
    )
    shutil.copy2(pilot_network, release / "input/network.xml.gz")
    release_signal_root = release / "input" / f"traffic_signals_{args.period}"
    shutil.copytree(pilot_signals, release_signal_root)
    (release / "app").mkdir()
    shutil.copy2(jar, release / "app" / jar.name)
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    run.mkdir()
    config = run / (
        f"config_stage11_traffic_signals_{args.period}_it0_it{args.last_iteration}.xml"
    )
    write_run_config(
        template,
        config,
        release,
        run,
        args.last_iteration,
        "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz",
    )
    rewrite_household_run_config(config)
    configure_physical_school_bus(config)
    write_config(config, release, run, args.period)
    set_qsim_stuck_time(config, args.stuck_time)

    household_candidates = release / "input/household_joint_plan_potential_candidates.csv"
    student_candidates = release / "input/school_bus_plan_candidates_5pct_v6"
    require_regular(household_candidates)
    for name in ("school_trip_universe_v6.csv", "school_bus_physical_route_candidates_v6.csv"):
        require_regular(student_candidates / name)

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
        f"--household-joint-plan-candidates={household_candidates}",
        f"--student-school-mode-candidates={student_candidates}",
        "--physical-nontaxi-modes",
        "--unlimited-ordinary-pt-capacity",
        "--traffic-signals",
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
        "objective": f"{pilot_version} traffic-signal integrated physical-mode mechanical gate",
        "pilot_version": pilot_version,
        "evidence_period": args.period,
        "stage_mapping_status": pilot_summary.get("stage_mapping_status", "unspecified"),
        "junctions": active_junctions,
        "active_junctions": active_junctions,
        "signal_movements": pilot_summary.get("signal_movement_count"),
        "controlled_approach_links": pilot_summary.get("controlled_approach_link_count"),
        "signal_plan_count": pilot_summary.get("signal_plan_count"),
        "public_diagram_junction_count": (
            validation_summary.get("public_diagram_junction_count")
            if validation_summary is not None else None
        ),
        "diagram_special_treatment_count": (
            validation_summary.get("diagram_special_treatment_count")
            if validation_summary is not None else None
        ),
        "amber_s": pilot_summary.get("amber_s"),
        "red_amber_s": pilot_summary.get("red_amber_s"),
        "minimum_intergreen_s": pilot_summary.get("minimum_intergreen_s"),
        "controller_onset_gap_s": pilot_summary.get("controller_onset_gap_s"),
        "timing_semantics": (
            "MATSim event intergreen = configured onset gap + redAmber - amber"
        ),
        "capacity_treatment": "audited final approach links replaced by TPDM saturation proxy",
        "base_release": str(base),
        "release_root": str(release),
        "run_root": str(run),
        "last_iteration": args.last_iteration,
        "stuck_time_s": args.stuck_time,
        "ordinary_innovation": "frozen; KeepLastSelected only",
        "runtime_conflict_boundary": (
            "multi-node physical junction clusters use audited fixed-stage separation; "
            "no fabricated single-node conflictingDirections file"
        ),
        "command": command,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
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
    raise SystemExit(main())
