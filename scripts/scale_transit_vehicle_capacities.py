"""Scale MATSim transit vehicle type capacities.

This is useful when a sampled population should interact with a sampled or
otherwise reduced public-transport capacity. Vehicle instances and departures
are not changed; only seats/standing room of each vehicleType are scaled.
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import time
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "transit" / "fuzhou_transit_matsim_integrated_20260709" / "transitVehicles.xml.gz"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "transit" / "fuzhou_transit_matsim_integrated_20260709_ptcap20"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=pathlib.Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--capacity-factor", type=float, default=0.20)
    return parser.parse_args()


def open_text(path: pathlib.Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode, encoding="utf-8", newline="\n")
    return path.open(mode, encoding="utf-8", newline="\n")


def scaled_int(value: str | None, factor: float) -> int:
    try:
        raw = float(value or "0")
    except ValueError:
        raw = 0.0
    if raw <= 0:
        return 0
    return max(1, int(round(raw * factor)))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def main() -> None:
    args = parse_args()
    started = time.time()
    if not args.input.exists():
        raise FileNotFoundError(args.input)
    if args.capacity_factor <= 0:
        raise ValueError("--capacity-factor must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "transitVehicles.xml.gz"

    with open_text(args.input, "rt") as source:
        tree = ET.parse(source)
    root = tree.getroot()
    ET.register_namespace("", "http://www.matsim.org/files/dtd")

    rows: list[dict] = []
    for vehicle_type in root.iter():
        if local_name(vehicle_type.tag) != "vehicleType":
            continue
        capacity = next((child for child in vehicle_type if local_name(child.tag) == "capacity"), None)
        if capacity is None:
            continue
        old_seats = capacity.get("seats", "0")
        old_standing = capacity.get("standingRoomInPersons", "0")
        new_seats = scaled_int(old_seats, args.capacity_factor)
        new_standing = scaled_int(old_standing, args.capacity_factor)
        capacity.set("seats", str(new_seats))
        capacity.set("standingRoomInPersons", str(new_standing))
        rows.append(
            {
                "vehicle_type": vehicle_type.get("id", ""),
                "old_seats": old_seats,
                "old_standingRoomInPersons": old_standing,
                "new_seats": new_seats,
                "new_standingRoomInPersons": new_standing,
                "old_total_capacity": int(float(old_seats)) + int(float(old_standing)),
                "new_total_capacity": new_seats + new_standing,
            }
        )

    with open_text(output, "wt") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(handle, encoding="unicode", xml_declaration=False, short_empty_elements=True)

    qa_csv = args.output_dir / "transit_vehicle_capacity_scaling.csv"
    with qa_csv.open("w", encoding="utf-8", newline="\n") as handle:
        columns = [
            "vehicle_type",
            "old_seats",
            "old_standingRoomInPersons",
            "new_seats",
            "new_standingRoomInPersons",
            "old_total_capacity",
            "new_total_capacity",
        ]
        handle.write(",".join(columns) + "\n")
        for row in rows:
            handle.write(",".join(str(row[column]) for column in columns) + "\n")

    summary = {
        "created_by": "scripts/scale_transit_vehicle_capacities.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "input": str(args.input),
        "output": str(output),
        "capacity_factor": args.capacity_factor,
        "vehicle_type_count": len(rows),
        "vehicle_types": rows,
    }
    summary_path = args.output_dir / "transit_vehicle_capacity_scaling_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
