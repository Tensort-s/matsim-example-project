#!/usr/bin/env python3
"""Prepare an append-only Hong Kong MATSim server deployment bundle."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import heapq
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
SCENARIO_RELATIVE = Path(
    "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
)
SUPPLY_RELATIVE = Path(
    "transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_"
    "mixed_bus_pcu005_ferry_core_v1_cap010"
)
CONFIG_NAME = "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
SERVER_BUILD_COMMAND = "./mvnw -DskipTests package"
MATSIM_VERSION = "2026.0"
EXPECTED_INPUT_SHA256 = {
    "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml":
        "75f9c8e82b6fee4141d3544c931309ca23abce76fe6d170c840acb007e1b115c",
    "input/plans_routed_5pct_v2.xml.gz":
        "c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea",
    "input/facilities_5pct_v2.xml.gz":
        "74775533a7022b248d37197dbc94d27f239239aca386df75c7a391cc277ef10e",
    "input/privateVehicles_5pct.xml.gz":
        "5a48b2afe404afaa6864a465c527277605a276e54cd879d3971261186938c994",
    "input/network.xml.gz":
        "dfc696442913a6d16a1ca1be7e5a332ec5762012190ed43a38f05493905ddc95",
    "input/transitSchedule_5pct.xml.gz":
        "eb92e6c7b3c2746313be92b8c88d51bc645d1db3c6605d1f4b472f27c9896aed",
    "input/transitVehicles_10pct.xml.gz":
        "16a6b89f77d3827ded06641869bf4e4c5168fb718356c1fe04e9f9249fdd7429",
}
STALE_ACTIVE_INPUT_FRAGMENTS = (
    "typical_weekday_5pct_v1",
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_v1",
    "transitVehicles_5pct.xml.gz",
    "config_hong_kong_5pct_50it.xml",
)
REQUIRED_RUNTIME_CLASSES = (
    "org/matsim/project/hongkong/taxi/"
    "HongKongTaxiFareScoringComponentFactory.class",
    "org/matsim/project/hongkong/pt/"
    "HongKongPtFareScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarEnergyScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarTollScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarParkingScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarMarginalCostScoringComponentFactory.class",
    "org/matsim/project/hongkong/scoring/"
    "HongKongMultimodalScoringFunctionFactory.class",
)
SMOKE_PERSON_COUNT = 7_716


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_repository_identity(source_commit_sha: str) -> None:
    if len(source_commit_sha) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit_sha
    ):
        raise ValueError("Source commit must be a full lowercase Git SHA")
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != source_commit_sha:
        raise ValueError(
            f"Repository HEAD mismatch: expected {source_commit_sha}, got {head}"
        )
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise ValueError("Repository must be clean before bundle preparation")


def current_input_sources(data_root: Path) -> dict[str, Path]:
    scenario = data_root / SCENARIO_RELATIVE
    supply = data_root / SUPPLY_RELATIVE
    return {
        "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml":
            scenario / CONFIG_NAME,
        "input/network.xml.gz": supply / "network.xml.gz",
        "input/transitSchedule_5pct.xml.gz":
            supply / "transitSchedule_5pct.xml.gz",
        "input/transitVehicles_10pct.xml.gz":
            supply / "transitVehicles_10pct.xml.gz",
        "input/plans_routed_5pct_v2.xml.gz":
            scenario / "plans_routed_5pct_v2.xml.gz",
        "input/facilities_5pct_v2.xml.gz":
            scenario / "facilities_5pct_v2.xml.gz",
        "input/privateVehicles_5pct.xml.gz":
            scenario / "privateVehicles_5pct.xml.gz",
    }


def verify_current_inputs(sources: dict[str, Path]) -> dict[str, str]:
    if set(sources) != set(EXPECTED_INPUT_SHA256):
        raise ValueError("Current input inventory differs from the Stage 8D lock")
    actual: dict[str, str] = {}
    for relative, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        normalized = source.as_posix()
        stale = [
            fragment
            for fragment in STALE_ACTIVE_INPUT_FRAGMENTS
            if fragment in normalized
        ]
        if stale:
            raise ValueError(
                f"Stale v1/pre-Ferry input is prohibited: {source}: {stale}"
            )
        digest = sha256_file(source)
        expected = EXPECTED_INPUT_SHA256[relative]
        if digest != expected:
            raise ValueError(
                f"Locked input checksum mismatch for {relative}: "
                f"expected {expected}, got {digest}"
            )
        actual[relative] = digest
    return actual


def verify_fat_jar(path: Path) -> tuple[str, list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    missing = [name for name in REQUIRED_RUNTIME_CLASSES if name not in names]
    if missing:
        raise ValueError(
            "Fat JAR is missing Stage 8C Taxi/PT/Car runtime classes: "
            + ", ".join(missing)
        )
    return sha256_file(path), list(REQUIRED_RUNTIME_CLASSES)


def assert_new_path(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing path: {path}")


def copy_new(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    assert_new_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_new_text(path: Path, text: str, executable: bool = False) -> None:
    assert_new_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(0o750)


def select_smoke_person_ids(plans_path: Path, count: int) -> set[str]:
    heap: list[tuple[int, str]] = []
    with gzip.open(plans_path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag != "person":
                continue
            person_id = element.attrib["id"]
            score = int.from_bytes(
                hashlib.sha256(person_id.encode("utf-8")).digest(),
                "big",
            )
            item = (-score, person_id)
            if len(heap) < count:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
            element.clear()
    if len(heap) != count:
        raise ValueError(f"Requested {count} people, found only {len(heap)}")
    return {person_id for _, person_id in heap}


def write_smoke_plans(
    input_path: Path,
    output_path: Path,
    selected_ids: set[str],
) -> int:
    assert_new_path(output_path)
    written = 0
    with gzip.open(input_path, "rb") as source, gzip.open(
        output_path, "wt", encoding="utf-8", newline="\n"
    ) as destination:
        destination.write('<?xml version="1.0" encoding="utf-8"?>\n')
        destination.write(
            '<!DOCTYPE population SYSTEM '
            '"http://www.matsim.org/files/dtd/population_v6.dtd">\n\n'
        )
        destination.write("<population>\n")
        destination.write(
            '\t<attributes>\n'
            '\t\t<attribute name="coordinateReferenceSystem" '
            'class="java.lang.String">EPSG:32650</attribute>\n'
            '\t</attributes>\n'
        )
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag != "person":
                continue
            if element.attrib["id"] in selected_ids:
                destination.write(ET.tostring(element, encoding="unicode"))
                destination.write("\n")
                written += 1
            element.clear()
        destination.write("</population>\n")
    if written != len(selected_ids):
        raise ValueError(f"Expected {len(selected_ids)} people, wrote {written}")
    with gzip.open(output_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    if len(root.findall("./person")) != written:
        raise ValueError("Smoke plans XML verification failed")
    return written


def set_param(module: ET.Element, name: str, value: str) -> None:
    for param in module.findall("./param"):
        if param.attrib.get("name") == name:
            param.set("value", value)
            return
    ET.SubElement(module, "param", {"name": name, "value": value})


def get_module(root: ET.Element, name: str) -> ET.Element:
    for module in root.findall("./module"):
        if module.attrib.get("name") == name:
            return module
    return ET.SubElement(root, "module", {"name": name})


def write_server_config(
    template: Path,
    output: Path,
    release_root: str,
    plans_name: str,
    output_name: str,
    last_iteration: int,
) -> None:
    root = ET.parse(template).getroot()
    paths = {
        ("network", "inputNetworkFile"): "input/network.xml.gz",
        ("plans", "inputPlansFile"): f"input/{plans_name}",
        ("facilities", "inputFacilitiesFile"):
            "input/facilities_5pct_v2.xml.gz",
        ("vehicles", "vehiclesFile"): "input/privateVehicles_5pct.xml.gz",
        ("transit", "transitScheduleFile"): "input/transitSchedule_5pct.xml.gz",
        ("transit", "vehiclesFile"): "input/transitVehicles_10pct.xml.gz",
    }
    for (module_name, param_name), relative in paths.items():
        set_param(
            get_module(root, module_name),
            param_name,
            f"{release_root}/{relative}",
        )
    controller = get_module(root, "controller")
    set_param(controller, "firstIteration", "0")
    set_param(controller, "lastIteration", str(last_iteration))
    set_param(
        controller,
        "outputDirectory",
        f"{release_root}/runs/{output_name}/output",
    )
    set_param(controller, "overwriteFiles", "failIfDirectoryExists")
    interval = "1" if last_iteration <= 1 else "10"
    set_param(controller, "writeEventsInterval", interval)
    set_param(controller, "writePlansInterval", interval)
    set_param(controller, "writeSnapshotsInterval", "0")

    assert_new_path(output)
    with output.open("wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(
            '<!DOCTYPE config SYSTEM '
            '"http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        )
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")


def worker_script(release_root: str, config_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT={release_root!r}
case "$(readlink -m "$ROOT")" in
  /mnt/DiskM/by/*) ;;
  *) printf '%s\\n' "Unsafe ROOT: $ROOT" >&2; exit 90 ;;
esac
export HOME="$ROOT/home"
export TMPDIR="$ROOT/tmp"
export XDG_CACHE_HOME="$ROOT/home/.cache"
export JAVA_HOME="$ROOT/runtime/jdk-25"
export PATH="$JAVA_HOME/bin:/usr/bin:/bin"
export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$ROOT/tmp -Djava.util.prefs.userRoot=$ROOT/home/.java"
set +e
/usr/bin/time -v "$JAVA_HOME/bin/java" -Xms16g -Xmx96g \\
  -cp "$ROOT/app/matsim-example-project-0.0.1-SNAPSHOT.jar" \\
  org.matsim.project.RunHongKong5Pct \\
  "$ROOT/config/{config_name}" unused --simulate
rc=$?
set -e
set -o noclobber
printf '%s\\n' "$rc" > "$JOB_DIR/exit_code.txt"
exit "$rc"
"""


def launcher_script(release_root: str, job_name: str, worker_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
set -o noclobber
ROOT={release_root!r}
case "$(readlink -m "$ROOT")" in
  /mnt/DiskM/by/*) ;;
  *) printf '%s\\n' "Unsafe ROOT: $ROOT" >&2; exit 90 ;;
esac
JOB_DIR="$ROOT/runs/{job_name}"
test ! -e "$JOB_DIR"
mkdir "$JOB_DIR"
export JOB_DIR
LOG="$JOB_DIR/stdout_stderr.log"
PID_FILE="$JOB_DIR/pid.txt"
test ! -e "$LOG"
test ! -e "$PID_FILE"
nohup "$ROOT/scripts/{worker_name}" > "$LOG" 2>&1 &
pid=$!
printf '%s\\n' "$pid" > "$PID_FILE"
printf 'started pid=%s job=%s\\n' "$pid" "$JOB_DIR"
"""


def status_script(release_root: str, job_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT={release_root!r}
JOB_DIR="$ROOT/runs/{job_name}"
case "$(readlink -m "$JOB_DIR")" in
  /mnt/DiskM/by/*) ;;
  *) printf '%s\\n' "Unsafe JOB_DIR: $JOB_DIR" >&2; exit 90 ;;
esac
if test -f "$JOB_DIR/exit_code.txt"; then
  printf 'completed exit_code='
  cat "$JOB_DIR/exit_code.txt"
elif test -f "$JOB_DIR/pid.txt"; then
  pid="$(cat "$JOB_DIR/pid.txt")"
  if kill -0 "$pid" 2>/dev/null; then
    printf 'running pid=%s\\n' "$pid"
  else
    printf 'process_not_running_without_exit_code pid=%s\\n' "$pid"
  fi
else
  printf 'not_started\\n'
fi
if test -f "$JOB_DIR/stdout_stderr.log"; then
  tail -30 "$JOB_DIR/stdout_stderr.log"
fi
"""


def validate_release_root(value: str) -> str:
    normalized = value.rstrip("/")
    if not normalized.startswith("/mnt/DiskM/by/"):
        raise ValueError("Release root must be below /mnt/DiskM/by")
    return normalized


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    verify_repository_identity(args.source_commit_sha)
    release_root = validate_release_root(args.release_root)
    assert_new_path(args.staging_dir)
    assert_new_path(args.bundle_path)
    assert_new_path(args.deployment_manifest)
    if args.build_command != SERVER_BUILD_COMMAND:
        raise ValueError(
            f"Server build command must be exact: {SERVER_BUILD_COMMAND}"
        )
    if args.matsim_version != MATSIM_VERSION:
        raise ValueError(
            f"MATSim version must be {MATSIM_VERSION}, got {args.matsim_version}"
        )
    if not args.java_version.startswith("25"):
        raise ValueError("The server build must use Linux JDK 25")
    jar_hash, runtime_classes = verify_fat_jar(args.fat_jar)
    if not args.jdk_archive.is_file():
        raise FileNotFoundError(args.jdk_archive)
    jdk_hash = sha256_file(args.jdk_archive)
    if jdk_hash != args.jdk_sha256:
        raise ValueError(f"JDK checksum mismatch: {jdk_hash}")
    current_sources = current_input_sources(args.data_root)
    input_hashes = verify_current_inputs(current_sources)
    args.staging_dir.mkdir(parents=True)
    for relative in (
        "app",
        "archives",
        "config",
        "home",
        "input",
        "logs",
        "manifests",
        "runtime/jdk-25",
        "runs",
        "scripts",
        "tmp",
    ):
        (args.staging_dir / relative).mkdir(parents=True, exist_ok=False)

    scenario = args.data_root / SCENARIO_RELATIVE
    sources = {
        "app/matsim-example-project-0.0.1-SNAPSHOT.jar": args.fat_jar,
        "archives/OpenJDK25U-jdk_x64_linux_hotspot_25.0.3_9.tar.gz": args.jdk_archive,
        **{
            relative: source
            for relative, source in current_sources.items()
            if not relative.startswith("config/")
        },
    }
    for relative, source in sources.items():
        copy_new(source, args.staging_dir / relative)

    formal_plans = args.staging_dir / "input/plans_routed_5pct_v2.xml.gz"
    selected = select_smoke_person_ids(formal_plans, SMOKE_PERSON_COUNT)
    smoke_count = write_smoke_plans(
        formal_plans,
        args.staging_dir / "input/plans_smoke_0p1.xml.gz",
        selected,
    )
    write_server_config(
        scenario / CONFIG_NAME,
        args.staging_dir / "config/config_smoke_qsim.xml",
        release_root,
        "plans_smoke_0p1.xml.gz",
        "smoke_qsim_v1",
        0,
    )
    write_server_config(
        scenario / CONFIG_NAME,
        args.staging_dir / "config/config_formal_50it.xml",
        release_root,
        "plans_routed_5pct_v2.xml.gz",
        "formal_50it_v1",
        50,
    )

    scripts = {
        "scripts/smoke_worker.sh": worker_script(
            release_root, "config_smoke_qsim.xml"
        ),
        "scripts/formal_worker.sh": worker_script(
            release_root, "config_formal_50it.xml"
        ),
        "scripts/run_smoke.sh": launcher_script(
            release_root, "smoke_qsim_v1", "smoke_worker.sh"
        ),
        "scripts/run_formal_50it.sh": launcher_script(
            release_root, "formal_50it_v1", "formal_worker.sh"
        ),
        "scripts/status_smoke.sh": status_script(
            release_root, "smoke_qsim_v1"
        ),
        "scripts/status_formal_50it.sh": status_script(
            release_root, "formal_50it_v1"
        ),
    }
    for relative, content in scripts.items():
        write_new_text(args.staging_dir / relative, content, executable=True)

    source_rows: list[dict[str, Any]] = []
    for path in sorted(args.staging_dir.rglob("*")):
        if not path.is_file() or "manifests" in path.parts:
            continue
        relative = path.relative_to(args.staging_dir).as_posix()
        source = str(sources.get(relative, "generated"))
        source_rows.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "source": source,
            }
        )
    manifest_path = args.staging_dir / "manifests/SOURCE_MANIFEST.csv"
    with manifest_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(source_rows[0]))
        writer.writeheader()
        writer.writerows(source_rows)

    metadata = {
        "source_commit_sha": args.source_commit_sha,
        "release_root": release_root,
        "fat_jar_sha256": jar_hash,
        "required_runtime_classes": runtime_classes,
        "build_command": args.build_command,
        "prepare_command": shlex.join([sys.executable, *sys.argv]),
        "java_version": args.java_version,
        "maven_version": args.maven_version,
        "matsim_version": args.matsim_version,
        "locked_input_sha256": input_hashes,
        "locked_config_template": str(
            current_sources[
                "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
            ]
        ),
        "smoke_person_count": smoke_count,
        "formal_person_count": 385_820,
        "flow_capacity_factor": 0.1,
        "storage_capacity_factor": 0.1,
        "bus_pcu": 0.125,
        "gmb_pcu": 0.075,
        "transit_departures": 159_967,
        "formal_iterations": 50,
        "formal_output_interval": 10,
        "formal_run_started_by_deployment": False,
        "jdk_sha256": jdk_hash,
        "append_only_remote_policy": True,
        "stale_v1_or_pre_ferry_input_allowed": False,
    }
    write_new_text(
        args.staging_dir / "manifests/DEPLOYMENT_METADATA.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )
    checksums = []
    for path in sorted(args.staging_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            checksums.append(
                f"{sha256_file(path)}  {path.relative_to(args.staging_dir).as_posix()}"
            )
    write_new_text(
        args.staging_dir / "manifests/SHA256SUMS.txt",
        "\n".join(checksums) + "\n",
    )

    def normalize_tar_permissions(info: tarfile.TarInfo) -> tarfile.TarInfo:
        if info.isdir():
            info.mode = 0o750
        elif info.name.startswith("scripts/") and info.name.endswith(".sh"):
            info.mode = 0o750
        else:
            info.mode = 0o640
        return info

    with tarfile.open(args.bundle_path, "x") as archive:
        for child in sorted(args.staging_dir.iterdir()):
            archive.add(
                child,
                arcname=child.name,
                recursive=True,
                filter=normalize_tar_permissions,
            )
    bundle_summary = {
        **metadata,
        "staging_dir": str(args.staging_dir),
        "bundle_path": str(args.bundle_path),
        "bundle_size_bytes": args.bundle_path.stat().st_size,
        "bundle_sha256": sha256_file(args.bundle_path),
        "release_file_count": sum(
            path.is_file() for path in args.staging_dir.rglob("*")
        ),
    }
    deployment_manifest = {
        "schema_version":
            "hong_kong_exact_sha_server_bundle_deployment_manifest_v1",
        "status": "prepared_not_uploaded_not_run",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        **bundle_summary,
        "deployment_manifest_path": str(args.deployment_manifest),
        "server_upload_performed": False,
        "server_run_performed": False,
    }
    write_new_text(
        args.deployment_manifest,
        json.dumps(deployment_manifest, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(bundle_summary, ensure_ascii=False, indent=2))
    return bundle_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--source-commit-sha",
        required=True,
    )
    parser.add_argument("--fat-jar", type=Path, required=True)
    parser.add_argument("--jdk-archive", type=Path, required=True)
    parser.add_argument(
        "--jdk-sha256",
        default="69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f",
    )
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    parser.add_argument("--build-command", default=SERVER_BUILD_COMMAND)
    parser.add_argument("--java-version", required=True)
    parser.add_argument("--maven-version", required=True)
    parser.add_argument("--matsim-version", default=MATSIM_VERSION)
    return parser.parse_args()


def main() -> None:
    build_bundle(parse_args())


if __name__ == "__main__":
    main()
