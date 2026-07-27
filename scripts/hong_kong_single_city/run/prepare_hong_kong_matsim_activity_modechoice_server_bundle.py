#!/usr/bin/env python3
"""Prepare an append-only server bundle for the Hong Kong v2 MATSim run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_PROJECT = Path(r"F:\Matsim\matsim-example-project")
DEFAULT_RELEASE = "/mnt/DiskM/by/hk_matsim_5pct_activity_modechoice_ferry_cap010_v1"
OLD_RELEASE = "/mnt/DiskM/by/hk_matsim_5pct_mixed_pcu005_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_new(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def param(module: ET.Element, name: str) -> ET.Element:
    for element in module.findall("param"):
        if element.get("name") == name:
            return element
    raise KeyError(f"Missing parameter {module.get('name')}.{name}")


def module(root: ET.Element, name: str) -> ET.Element:
    for element in root.findall("module"):
        if element.get("name") == name:
            return element
    raise KeyError(f"Missing module {name}")


def write_server_config(source: Path, target: Path, release: str) -> None:
    tree = ET.parse(source)
    root = tree.getroot()

    replacements = {
        ("network", "inputNetworkFile"): f"{release}/input/network.xml.gz",
        ("plans", "inputPlansFile"): f"{release}/input/plans_routed_5pct_v2.xml.gz",
        ("facilities", "inputFacilitiesFile"): f"{release}/input/facilities_5pct_v2.xml.gz",
        ("vehicles", "vehiclesFile"): f"{release}/input/privateVehicles_5pct.xml.gz",
        ("transit", "transitScheduleFile"): f"{release}/input/transitSchedule_5pct.xml.gz",
        ("transit", "vehiclesFile"): f"{release}/input/transitVehicles_10pct.xml.gz",
        ("controller", "outputDirectory"): f"{release}/runs/formal_50it_v1/output",
    }
    for (module_name, parameter_name), value in replacements.items():
        param(module(root, module_name), parameter_name).set("value", value)

    param(module(root, "global"), "numberOfThreads").set("value", "8")
    param(module(root, "qsim"), "numberOfThreads").set("value", "8")
    param(module(root, "qsim"), "flowCapacityFactor").set("value", "0.1")
    param(module(root, "qsim"), "storageCapacityFactor").set("value", "0.1")
    param(module(root, "controller"), "firstIteration").set("value", "0")
    param(module(root, "controller"), "lastIteration").set("value", "50")
    param(module(root, "controller"), "overwriteFiles").set(
        "value", "failIfDirectoryExists"
    )
    param(module(root, "controller"), "writeEventsInterval").set("value", "10")
    param(module(root, "controller"), "writePlansInterval").set("value", "10")

    ET.indent(tree, space="  ")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        stream.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        stream.write(
            b'<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        )
        tree.write(stream, encoding="utf-8", xml_declaration=False)


def write_scripts(staging: Path, release: str, old_release: str) -> None:
    install = f"""#!/usr/bin/env bash
set -euo pipefail

RELEASE={release!r}
SOURCE_RELEASE={old_release!r}
ARCHIVE="${{1:?bundle archive path is required}}"

case "$RELEASE" in
  /mnt/DiskM/by/*) ;;
  *) echo "unsafe release path: $RELEASE" >&2; exit 2 ;;
esac
case "$SOURCE_RELEASE" in
  /mnt/DiskM/by/*) ;;
  *) echo "unsafe source release path: $SOURCE_RELEASE" >&2; exit 2 ;;
esac
case "$ARCHIVE" in
  /mnt/DiskM/by/*) ;;
  *) echo "unsafe archive path: $ARCHIVE" >&2; exit 2 ;;
esac

if [[ -e "$RELEASE" ]]; then
  echo "release already exists: $RELEASE" >&2
  exit 3
fi
[[ -d "$SOURCE_RELEASE/runtime" ]]
[[ -d "$SOURCE_RELEASE/app" ]]
[[ -f "$ARCHIVE" ]]

mkdir "$RELEASE"
cp -a "$SOURCE_RELEASE/runtime" "$RELEASE/runtime"
cp -a "$SOURCE_RELEASE/app" "$RELEASE/app"
tar --keep-old-files -xzf "$ARCHIVE" -C "$RELEASE"
cd "$RELEASE"
sha256sum -c manifests/SHA256SUMS.txt
chmod 0755 "$RELEASE/scripts/"*.sh
"$RELEASE/runtime/jdk-25/bin/java" -version
test -f "$RELEASE/app/matsim-example-project-0.0.1-SNAPSHOT.jar"
test -f "$RELEASE/input/network.xml.gz"
test -f "$RELEASE/input/transitSchedule_5pct.xml.gz"
test -f "$RELEASE/input/transitVehicles_10pct.xml.gz"
test -f "$RELEASE/input/plans_routed_5pct_v2.xml.gz"
echo "installed $RELEASE"
"""

    worker = f"""#!/usr/bin/env bash
set -u

RELEASE={release!r}
RUN="$RELEASE/runs/formal_50it_v1"
JAVA="$RELEASE/runtime/jdk-25/bin/java"
JAR="$RELEASE/app/matsim-example-project-0.0.1-SNAPSHOT.jar"
CONFIG="$RELEASE/config/config_formal_50it_v1.xml"

export HOME="$RELEASE/home"
export TMPDIR="$RELEASE/tmp"
export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$RELEASE/tmp -Djava.util.prefs.userRoot=$RELEASE/home/.java -Djava.util.prefs.systemRoot=$RELEASE/home/.java-system"

set +e
/usr/bin/time -v "$JAVA" -Xms16g -Xmx96g -cp "$JAR" \
  org.matsim.project.RunHongKong5Pct "$CONFIG" unused --simulate \
  >"$RUN/run.log" 2>&1
status=$?
set -e
printf '%s\\n' "$status" >"$RUN/exit_code.txt"
if [[ "$status" -eq 0 ]]; then
  printf 'completed exit_code=0\\n' >"$RUN/status.txt"
else
  printf 'failed exit_code=%s\\n' "$status" >"$RUN/status.txt"
fi
exit "$status"
"""

    launch = f"""#!/usr/bin/env bash
set -euo pipefail

RELEASE={release!r}
RUN="$RELEASE/runs/formal_50it_v1"
WORKER="$RELEASE/scripts/run_formal_50it_worker.sh"

case "$RUN" in
  /mnt/DiskM/by/*) ;;
  *) echo "unsafe run path: $RUN" >&2; exit 2 ;;
esac
if [[ -e "$RUN" ]]; then
  echo "run directory already exists: $RUN" >&2
  exit 3
fi
mkdir "$RUN"
printf 'starting\\n' >"$RUN/status.txt"
nohup "$WORKER" </dev/null >"$RUN/launcher.log" 2>&1 &
pid=$!
printf '%s\\n' "$pid" >"$RUN/run.pid"
printf 'started pid=%s run=%s\\n' "$pid" "$RUN"
"""

    status = f"""#!/usr/bin/env bash
set -euo pipefail

RELEASE={release!r}
RUN="$RELEASE/runs/formal_50it_v1"

echo "release=$RELEASE"
if [[ ! -d "$RUN" ]]; then
  echo "status=not_started"
  exit 0
fi
if [[ -f "$RUN/run.pid" ]]; then
  pid=$(cat "$RUN/run.pid")
  echo "pid=$pid"
  if kill -0 "$pid" 2>/dev/null; then
    echo "process=running"
  else
    echo "process=stopped"
  fi
fi
if [[ -f "$RUN/status.txt" ]]; then
  echo -n "status="
  cat "$RUN/status.txt"
fi
if [[ -f "$RUN/exit_code.txt" ]]; then
  echo -n "exit_code="
  cat "$RUN/exit_code.txt"
fi
if [[ -f "$RUN/run.log" ]]; then
  grep -E "ITERATION [0-9]+ ENDS|ERROR|Exception|Shutdown" "$RUN/run.log" | tail -n 12 || true
  echo "--- log tail ---"
  tail -n 20 "$RUN/run.log"
fi
"""

    for filename, content in {
        "install_release.sh": install,
        "run_formal_50it_worker.sh": worker,
        "launch_formal_50it.sh": launch,
        "status_formal_50it.sh": status,
    }.items():
        path = staging / "scripts" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--release-root", default=DEFAULT_RELEASE)
    parser.add_argument("--runtime-source-release", default=OLD_RELEASE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project = args.project_root.resolve()
    staging = args.staging_dir.resolve()
    archive = args.archive.resolve()

    if staging.exists():
        raise FileExistsError(staging)
    if archive.exists():
        raise FileExistsError(archive)
    staging.mkdir(parents=True)

    plan_root = (
        project
        / "data"
        / "matsim_agents"
        / "hongkong"
        / "typical_weekday_5pct_v2_activity_modechoice"
    )
    supply_root = (
        project
        / "data"
        / "transit"
        / "hongkong"
        / "processed"
        / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
    )

    sources = {
        "input/plans_routed_5pct_v2.xml.gz": plan_root / "plans_routed_5pct_v2.xml.gz",
        "input/facilities_5pct_v2.xml.gz": plan_root / "facilities_5pct_v2.xml.gz",
        "input/privateVehicles_5pct.xml.gz": plan_root / "privateVehicles_5pct.xml.gz",
        "input/network.xml.gz": supply_root / "network.xml.gz",
        "input/transitSchedule_5pct.xml.gz": supply_root / "transitSchedule_5pct.xml.gz",
        "input/transitVehicles_10pct.xml.gz": supply_root / "transitVehicles_10pct.xml.gz",
    }
    manifest_rows = []
    for relative, source in sources.items():
        target = staging / relative
        copy_new(source, target)
        manifest_rows.append(
            {
                "relative_path": relative,
                "source_path": str(source),
                "bytes": source.stat().st_size,
                "sha256": sha256(source),
            }
        )

    config_target = staging / "config" / "config_formal_50it_v1.xml"
    write_server_config(
        plan_root / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml",
        config_target,
        args.release_root,
    )
    write_scripts(staging, args.release_root, args.runtime_source_release)

    for directory in ("home", "tmp", "logs", "runs"):
        (staging / directory).mkdir(exist_ok=True)
        (staging / directory / ".keep").write_text("", encoding="ascii")

    manifest_dir = staging / "manifests"
    manifest_dir.mkdir(exist_ok=True)
    with (manifest_dir / "SOURCE_MANIFEST.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["relative_path", "source_path", "bytes", "sha256"]
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    checksum_paths = [
        path
        for path in staging.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    with (manifest_dir / "SHA256SUMS.txt").open(
        "w", encoding="ascii", newline="\n"
    ) as stream:
        for path in sorted(checksum_paths):
            relative = path.relative_to(staging).as_posix()
            stream.write(f"{sha256(path)}  {relative}\n")

    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(staging.rglob("*")):
            tar.add(
                path,
                arcname=path.relative_to(staging).as_posix(),
                recursive=False,
            )

    print(f"staging={staging}")
    print(f"archive={archive}")
    print(f"archive_bytes={archive.stat().st_size}")
    print(f"archive_sha256={sha256(archive)}")
    print(f"release_root={args.release_root}")


if __name__ == "__main__":
    main()
