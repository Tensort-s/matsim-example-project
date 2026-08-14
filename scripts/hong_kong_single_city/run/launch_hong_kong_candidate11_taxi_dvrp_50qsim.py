#!/usr/bin/env python3
"""Prepare and launch immutable Candidate11 physical-Taxi DVRP runs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
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
ALLOWED_TAXI_PCU = (1.0, 0.75, 0.5, 0.25, 0.1)


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


RUN_PROFILES = {
    "formal-50": RunProfile(0, 49, 0.1, 15_500, 385_820),
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
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an immutable physical-Taxi release/run and launch it, or "
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
        help="Required for DVRP profiles and forbidden for gate-0-1-proxy.",
    )
    parser.add_argument(
        "--plans-input",
        type=Path,
        help="Override the plans file in the template; mandatory for smoke-0p5.",
    )
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--taxi-pcu", type=float, choices=ALLOWED_TAXI_PCU, default=1.0)
    parser.add_argument("--taxi-wait-utility-per-hour", type=float, default=-12.0)
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


def derive_config(
    template: Path,
    destination: Path,
    run: Path,
    profile: RunProfile,
    *,
    plans_input: Path | None = None,
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
    set_param(qsim, "stuckTime", "3600")
    set_param(qsim, "removeStuckVehicles", "false")
    if profile.taxi_execution == "dvrp":
        set_param(qsim, "simStarttimeInterpretation", "onlyUseStarttime")

    controller = module(root, "controller")
    updates = {
        "firstIteration": str(profile.first_iteration),
        "lastIteration": str(profile.last_iteration),
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

    replanning = module(root, "replanning")
    if profile.fixed_selected_plans:
        set_param(replanning, "fractionOfIterationsToDisableInnovation", "0.0")
        frozen_strategies = keep_last_selected_only(replanning)
    else:
        set_param(replanning, "fractionOfIterationsToDisableInnovation", "0.70")
        frozen_strategies = freeze_innovation_after_iteration(replanning, 34)

    subtour = module(root, "subtourModeChoice")
    set_param(subtour, "modes", "car,pt,walk,taxi")
    set_param(subtour, "chainBasedModes", "car")
    if plans_input is not None:
        set_param(module(root, "plans"), "inputPlansFile", str(plans_input))

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
) -> list[str]:
    command = [
        str(java), f"-Xms{xms}", f"-Xmx{xmx}", "-cp", str(jar),
        "org.matsim.project.RunHongKong5Pct", str(config), "unused",
        "--simulate", "--multimodal-costs", "--dynamic-car-costs",
        f"--pt-fare-root={cost_root / 'pt_fare_v1'}",
        f"--car-cost-root={cost_root / 'car_cost_v1'}",
        "--physical-nontaxi-modes", "--unlimited-ordinary-pt-capacity",
        "--traffic-signals",
        "--walk-overtime-scoring",
        f"--student-school-mode-candidates={runtime / 'input/school_bus_plan_candidates_5pct_v6'}",
    ]
    # Fixed gate/smoke plans are experienced physical itineraries from run14b.
    # Clearing their valid PT routes would discard that frozen network state and
    # can split a school-bus trip into inconsistent per-leg routing modes.  The
    # formal profile starts from the original generic Candidate11 plans, so it
    # still requires the established SwissRailRaptor rebuild.
    if not profile.fixed_selected_plans:
        command.append("--clear-pt-routes")
    if profile.taxi_execution == "dvrp":
        if fleet is None:
            raise ValueError("A Taxi fleet is required for DVRP command construction")
        command.extend([
            f"--taxi-dvrp-fleet={fleet}",
            f"--taxi-dvrp-pcu={taxi_pcu:g}",
            f"--taxi-wait-utility-per-hour={taxi_wait_utility_per_hour:g}",
        ])
    elif profile.taxi_execution == "proxy":
        if fleet is not None:
            raise ValueError("Proxy command construction must not receive a Taxi fleet")
        command.append("--fixed-plans-network-taxi-proxy")
    else:
        raise ValueError(f"Unsupported Taxi execution: {profile.taxi_execution}")
    if not profile.fixed_selected_plans:
        command.extend([
            f"--household-joint-plan-candidates={runtime / 'input/household_joint_plan_potential_candidates.csv'}",
            "--household-joint-plan-with-ordinary-innovation",
            f"--household-joint-selection-iterations={','.join(map(str, HOUSEHOLD_SELECTION_ITERATIONS))}",
        ])
        if "--all-person-network-taxi-innovation" not in command:
            command.append("--all-person-network-taxi-innovation")
    return command


def main() -> int:
    args = parse_args()
    profile = RUN_PROFILES[args.profile]
    if profile.requires_plans_override and args.plans_input is None:
        raise ValueError(f"--plans-input is required for profile {args.profile}")
    if args.profile == "formal-50" and args.plans_input is not None:
        raise ValueError("formal-50 must use the original Candidate11 plans from the template")
    if profile.taxi_execution == "dvrp" and args.taxi_fleet is None:
        raise ValueError(f"--taxi-fleet is required for profile {args.profile}")
    if profile.taxi_execution == "proxy" and args.taxi_fleet is not None:
        raise ValueError(f"--taxi-fleet is forbidden for profile {args.profile}")
    if profile.taxi_execution == "proxy" and (
        args.taxi_pcu != 1.0 or args.taxi_wait_utility_per_hour != -12.0
    ):
        raise ValueError("Proxy profile does not accept Taxi DVRP PCU/wait overrides")
    if args.taxi_wait_utility_per_hour >= 0:
        raise ValueError("Taxi wait utility per hour must be negative")

    runtime = safe(args.runtime_input_release, exists=True)
    previous = safe(args.previous_app_release, exists=True)
    template = safe(args.config_template, exists=True)
    payload_jar = safe(args.payload_jar, exists=True)
    source_fleet = safe(args.taxi_fleet, exists=True) if args.taxi_fleet else None
    plans_input = safe(args.plans_input, exists=True) if args.plans_input else None
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
    if not profile.fixed_selected_plans:
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
    cost_root = release / "data/transport_costs/hongkong"
    cost_root.mkdir(parents=True)
    shutil.copytree(pt_source, cost_root / "pt_fare_v1")
    shutil.copytree(car_source, cost_root / "car_cost_v1")
    for name in ("home", "tmp", "logs"):
        (release / name).mkdir()

    config = run / f"config_candidate11_taxi_dvrp_{args.profile}.xml"
    frozen_strategies = derive_config(
        template, config, run, profile, plans_input=plans_input
    )
    java = runtime / "runtime/jdk-25/bin/java"
    command = build_command(
        java=java,
        jar=jar,
        config=config,
        cost_root=cost_root,
        runtime=runtime,
        fleet=fleet,
        taxi_pcu=args.taxi_pcu,
        taxi_wait_utility_per_hour=args.taxi_wait_utility_per_hour,
        profile=profile,
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
        "objective": "Candidate11 physical Taxi DVRP with explicit fleet matching and waiting",
        "profile": args.profile,
        "qsim_iterations": list(
            range(profile.first_iteration, profile.last_iteration + 1)
        ),
        "global_threads": 16,
        "qsim_threads": 16,
        "flow_capacity_factor": profile.capacity_factor,
        "storage_capacity_factor": profile.capacity_factor,
        "stuck_time_s": 3600,
        "remove_stuck_vehicles": False,
        "output_interval": 10,
        "fixed_selected_plans": profile.fixed_selected_plans,
        "taxi_execution": profile.taxi_execution,
        "innovation_disable_after_iteration": None if profile.fixed_selected_plans else 34,
        "fraction_of_iterations_to_disable_innovation": (
            0.0 if profile.fixed_selected_plans else 0.70
        ),
        "frozen_innovative_strategies": (
            [] if profile.fixed_selected_plans else frozen_strategies
        ),
        "removed_replanning_strategies": (
            frozen_strategies if profile.fixed_selected_plans else []
        ),
        "protected_selection_target_iterations": (
            [] if profile.fixed_selected_plans else list(HOUSEHOLD_SELECTION_ITERATIONS)
        ),
        "household_joint_catalog_loaded": not profile.fixed_selected_plans,
        "student_school_catalog_loaded": True,
        "taxi": (
            {
                "execution": "dvrp",
                "fleet_size": actual_fleet_size,
                "pcu": args.taxi_pcu,
                "wait_utility_per_hour": args.taxi_wait_utility_per_hour,
                "fleet_source": str(source_fleet),
                "fleet_source_sha256": sha256(source_fleet),
                "fleet_release_copy": str(fleet),
                "fleet_release_sha256": sha256(fleet),
            }
            if source_fleet is not None and fleet is not None
            else {
                "execution": "proxy",
                "fleet_size": None,
                "pcu": 1.0,
                "wait_utility_per_hour": None,
                "proxy_contract": "person-local network Taxi; no cruising/deadheading/fleet matching",
            }
        ),
        "plans": {
            "effective_input": str(effective_plans),
            "override": str(plans_input) if plans_input else None,
            "population_size": population_audit.persons,
            "taxi_legs_in_plan_memory": population_audit.taxi_legs,
            "sha256": sha256(effective_plans),
        },
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
