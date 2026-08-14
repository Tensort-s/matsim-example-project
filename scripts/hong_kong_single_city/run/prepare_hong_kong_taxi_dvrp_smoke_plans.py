#!/usr/bin/env python3
"""Create an exact, stable person subsample from frozen experienced plans."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import io
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from contextlib import contextmanager

try:
    import zstandard
except ImportError:  # pragma: no cover - server fallback is exercised operationally
    zstandard = None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@contextmanager
def open_binary(path: Path):
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
    elif path.suffix.lower() == ".zst":
        if zstandard is not None:
            with path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as handle:
                    yield handle
        else:
            executable = shutil.which("zstdcat")
            if executable is None:
                raise RuntimeError("Reading .zst requires zstandard or zstdcat")
            process = subprocess.Popen(
                [executable, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            assert process.stdout is not None
            try:
                yield process.stdout
            finally:
                process.stdout.close()
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                return_code = process.wait()
                if process.stderr:
                    process.stderr.close()
                if return_code != 0:
                    raise RuntimeError(
                        f"zstdcat failed for {path} with exit {return_code}: {stderr.strip()}"
                    )
    else:
        with path.open("rb") as handle:
            yield handle


def stable_person_ids(path: Path, count: int) -> set[str]:
    heap: list[tuple[int, str]] = []
    found = 0
    with open_binary(path) as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if local_name(element.tag) != "person":
                continue
            found += 1
            person_id = element.attrib["id"]
            score = int.from_bytes(hashlib.sha256(person_id.encode("utf-8")).digest(), "big")
            item = (-score, person_id)
            if len(heap) < count:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
            element.clear()
    if len(heap) != count:
        raise ValueError(f"Requested {count} people but input contains {found}")
    return {person_id for _, person_id in heap}


def selected_plan(person: ET.Element) -> ET.Element | None:
    plans = [child for child in person if local_name(child.tag) == "plan"]
    return next(
        (plan for plan in plans if (plan.get("selected") or "").lower() in {"yes", "true", "1"}),
        plans[0] if len(plans) == 1 else None,
    )


def selected_taxi_legs(person: ET.Element) -> int:
    selected = selected_plan(person)
    if selected is None:
        return 0
    return sum(
        1 for child in selected
        if local_name(child.tag) == "leg" and child.get("mode") == "taxi"
    )


def write_subset(
    input_path: Path,
    output_path: Path,
    selected_ids: set[str] | None,
    *,
    expected_persons: int,
    selected_only: bool = False,
) -> dict:
    if output_path.exists():
        raise FileExistsError(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = taxi_legs = 0
    with output_path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as destination:
                destination.write('<?xml version="1.0" encoding="utf-8"?>\n')
                destination.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
                destination.write('<population>\n\t<attributes>\n')
                destination.write('\t\t<attribute name="coordinateReferenceSystem" class="java.lang.String">EPSG:32650</attribute>\n')
                destination.write('\t</attributes>\n')
                with open_binary(input_path) as source:
                    for _, person in ET.iterparse(source, events=("end",)):
                        if local_name(person.tag) != "person":
                            continue
                        if selected_ids is None or person.attrib["id"] in selected_ids:
                            if selected_only:
                                selected = selected_plan(person)
                                if selected is None:
                                    raise RuntimeError(
                                        f"Person {person.attrib['id']} has no unambiguous selected plan"
                                    )
                                activities = sum(
                                    1 for child in selected
                                    if local_name(child.tag) in {"act", "activity"}
                                )
                                if activities == 0:
                                    raise RuntimeError(
                                        f"Person {person.attrib['id']} selected plan has no activity"
                                    )
                                for plan in [
                                    child for child in person
                                    if local_name(child.tag) == "plan" and child is not selected
                                ]:
                                    person.remove(plan)
                            taxi_legs += selected_taxi_legs(person)
                            destination.write(ET.tostring(person, encoding="unicode"))
                            destination.write("\n")
                            written += 1
                        person.clear()
                destination.write("</population>\n")
    if written != expected_persons or taxi_legs == 0:
        raise RuntimeError(
            f"Frozen plans validation failed: people={written}/{expected_persons}, taxi_legs={taxi_legs}"
        )
    return {
        "persons": written,
        "selected_taxi_legs": taxi_legs,
        "selected_only": selected_only,
        "all_persons": selected_ids is None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-plans", type=Path, required=True)
    parser.add_argument("--output-plans", type=Path, required=True)
    parser.add_argument("--persons", type=int, default=38_582)
    parser.add_argument(
        "--all-persons",
        action="store_true",
        help="write every person in one pass; --persons becomes the expected count",
    )
    parser.add_argument(
        "--selected-only",
        action="store_true",
        help="retain exactly the selected plan and reject empty selected plans",
    )
    parser.add_argument("--qa-json", type=Path)
    args = parser.parse_args()
    if args.persons <= 0 or not args.input_plans.is_file():
        raise ValueError("A positive person count and existing input plans are required")
    ids = None if args.all_persons else stable_person_ids(args.input_plans, args.persons)
    result = write_subset(
        args.input_plans,
        args.output_plans,
        ids,
        expected_persons=args.persons,
        selected_only=args.selected_only,
    )
    result.update({"input_plans": str(args.input_plans.resolve()), "output_plans": str(args.output_plans.resolve())})
    if args.qa_json:
        if args.qa_json.exists():
            raise FileExistsError(args.qa_json)
        args.qa_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
