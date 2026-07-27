#!/usr/bin/env python3
"""Prepare append-only baseline and Ferry MATSim releases with simulated PT."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path


BASELINE_RELEASE = "/mnt/DiskM/by/hk_matsim_5pct_ptfixed_baseline_v1"
FERRY_RELEASE = "/mnt/DiskM/by/hk_matsim_5pct_ptfixed_ferry_activity_v1"
SHARED_RELEASE = "/mnt/DiskM/by/hk_matsim_ptfix_shared_v1"
BASELINE_SOURCE = "/mnt/DiskM/by/hk_matsim_5pct_mixed_pcu005_v1"
FERRY_SOURCE = "/mnt/DiskM/by/hk_matsim_5pct_activity_modechoice_ferry_cap010_v1"
JAR_NAME = "matsim-example-project-0.0.1-SNAPSHOT-ptfix-v1.jar"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module(root: ET.Element, name: str) -> ET.Element:
    for element in root.findall("module"):
        if element.get("name") == name:
            return element
    raise KeyError(name)


def parameter(module_element: ET.Element, name: str) -> ET.Element:
    for element in module_element.findall("param"):
        if element.get("name") == name:
            return element
    raise KeyError(f"{module_element.get('name')}.{name}")


def write_config(
    source: Path,
    target: Path,
    source_release: str,
    target_release: str,
    mode: str,
) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    for element in root.iter("param"):
        value = element.get("value")
        if value and source_release in value:
            element.set("value", value.replace(source_release, target_release))

    parameter(module(root, "transit"), "transitModes").set("value", "pt")
    parameter(module(root, "global"), "numberOfThreads").set("value", "8")
    parameter(module(root, "qsim"), "numberOfThreads").set("value", "8")
    parameter(module(root, "qsim"), "flowCapacityFactor").set("value", "0.1")
    parameter(module(root, "qsim"), "storageCapacityFactor").set("value", "0.1")

    controller = module(root, "controller")
    if mode == "smoke_it0":
        parameter(controller, "lastIteration").set("value", "0")
        parameter(controller, "writeEventsInterval").set("value", "1")
        parameter(controller, "writePlansInterval").set("value", "1")
    else:
        parameter(controller, "lastIteration").set("value", "50")
        parameter(controller, "writeEventsInterval").set("value", "10")
        parameter(controller, "writePlansInterval").set("value", "10")
    parameter(controller, "firstIteration").set("value", "0")
    parameter(controller, "overwriteFiles").set("value", "failIfDirectoryExists")
    parameter(controller, "outputDirectory").set(
        "value", f"{target_release}/runs/{mode}_v1/output"
    )

    ET.indent(tree, space="  ")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        stream.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        stream.write(
            b'<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        )
        tree.write(stream, encoding="utf-8", xml_declaration=False)


def write_release_scripts(staging: Path, release: str) -> None:
    root = staging / release.removeprefix("/mnt/DiskM/by/")
    worker = f"""#!/usr/bin/env bash
set -u
ROOT={release!r}
MODE="${{1:?mode is required}}"
case "$MODE" in smoke_it0|formal_50it) ;; *) exit 2 ;; esac
RUN="$ROOT/runs/${{MODE}}_v1"
CONFIG="$ROOT/config/config_${{MODE}}.xml"
JAVA="$ROOT/runtime/jdk-25/bin/java"
JAR={SHARED_RELEASE!r}/app/{JAR_NAME}
export HOME="$ROOT/home"
export TMPDIR="$ROOT/tmp"
export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$ROOT/tmp -Djava.util.prefs.userRoot=$ROOT/home/.java -Djava.util.prefs.systemRoot=$ROOT/home/.java-system"
set +e
/usr/bin/time -v "$JAVA" -Xms12g -Xmx64g -cp "$JAR" \
  org.matsim.project.RunHongKong5Pct "$CONFIG" unused \
  --simulate --clear-pt-routes >"$RUN/run.log" 2>&1
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
ROOT={release!r}
MODE="${{1:?mode is required}}"
case "$MODE" in smoke_it0|formal_50it) ;; *) exit 2 ;; esac
RUN="$ROOT/runs/${{MODE}}_v1"
if [[ -e "$RUN" ]]; then echo "run exists: $RUN" >&2; exit 3; fi
mkdir "$RUN"
printf 'starting\\n' >"$RUN/status.txt"
nohup "$ROOT/scripts/run_worker.sh" "$MODE" </dev/null >"$RUN/launcher.log" 2>&1 &
printf '%s\\n' "$!" >"$RUN/run.pid"
echo "started mode=$MODE pid=$!"
"""
    status = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT={release!r}
MODE="${{1:?mode is required}}"
RUN="$ROOT/runs/${{MODE}}_v1"
if [[ ! -d "$RUN" ]]; then echo not_started; exit 0; fi
if [[ -f "$RUN/run.pid" ]]; then
  pid=$(cat "$RUN/run.pid")
  if kill -0 "$pid" 2>/dev/null; then echo process=running; else echo process=stopped; fi
fi
cat "$RUN/status.txt" 2>/dev/null || true
grep "ITERATION .* ENDS" "$RUN/run.log" 2>/dev/null | tail -n 3 || true
tail -n 8 "$RUN/run.log" 2>/dev/null || true
"""
    for name, content in {
        "run_worker.sh": worker,
        "launch.sh": launch,
        "status.sh": status,
    }.items():
        path = root / "scripts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def write_installer(staging: Path) -> None:
    content = f"""#!/usr/bin/env bash
set -euo pipefail
BASELINE={BASELINE_RELEASE!r}
FERRY={FERRY_RELEASE!r}
SHARED={SHARED_RELEASE!r}
BASELINE_SOURCE={BASELINE_SOURCE!r}
FERRY_SOURCE={FERRY_SOURCE!r}
for path in "$BASELINE" "$FERRY" "$SHARED"; do
  case "$path" in /mnt/DiskM/by/*) ;; *) exit 2 ;; esac
done
for path in "$BASELINE" "$FERRY" "$SHARED"; do test -d "$path"; done
cp -al "$BASELINE_SOURCE/runtime" "$BASELINE/runtime"
cp -al "$BASELINE_SOURCE/input" "$BASELINE/input"
cp -al "$FERRY_SOURCE/runtime" "$FERRY/runtime"
cp -al "$FERRY_SOURCE/input" "$FERRY/input"
for root in "$BASELINE" "$FERRY"; do
  mkdir "$root/home" "$root/tmp" "$root/logs" "$root/runs"
  chmod 0755 "$root/scripts/"*.sh
done
test -f "$SHARED/app/{JAR_NAME}"
echo installed
"""
    path = staging / "install_ptfixed_parallel.sh"
    path.write_text(content, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-config", type=Path, required=True)
    parser.add_argument("--ferry-config", type=Path, required=True)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    staging = args.staging_dir.resolve()
    archive = args.archive.resolve()
    if staging.exists() or archive.exists():
        raise FileExistsError("staging directory and archive must be new")
    staging.mkdir(parents=True)

    releases = [
        (
            args.baseline_config,
            BASELINE_SOURCE,
            BASELINE_RELEASE,
        ),
        (
            args.ferry_config,
            FERRY_SOURCE,
            FERRY_RELEASE,
        ),
    ]
    for source_config, source_release, target_release in releases:
        root = staging / target_release.removeprefix("/mnt/DiskM/by/")
        for mode in ("smoke_it0", "formal_50it"):
            write_config(
                source_config,
                root / "config" / f"config_{mode}.xml",
                source_release,
                target_release,
                mode,
            )
        write_release_scripts(staging, target_release)

    jar_target = (
        staging
        / SHARED_RELEASE.removeprefix("/mnt/DiskM/by/")
        / "app"
        / JAR_NAME
    )
    jar_target.parent.mkdir(parents=True)
    shutil.copy2(args.jar, jar_target)
    write_installer(staging)

    checksum_file = staging / "SHA256SUMS.txt"
    with checksum_file.open("w", encoding="ascii", newline="\n") as stream:
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path != checksum_file:
                stream.write(
                    f"{sha256(path)}  {path.relative_to(staging).as_posix()}\n"
                )

    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(staging.rglob("*")):
            tar.add(
                path,
                arcname=path.relative_to(staging).as_posix(),
                recursive=False,
            )
    print(f"archive={archive}")
    print(f"bytes={archive.stat().st_size}")
    print(f"sha256={sha256(archive)}")


if __name__ == "__main__":
    main()
