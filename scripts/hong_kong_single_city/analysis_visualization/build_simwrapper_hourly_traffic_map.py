"""Build Hong Kong SimWrapper hourly car-traffic maps from MATSim events."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import contextmanager
from typing import BinaryIO, Iterator


ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
CAR_MODE = "car"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create Hong Kong SimWrapper hourly traffic map inputs."
    )
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--events", type=pathlib.Path)
    parser.add_argument("--network", type=pathlib.Path)
    parser.add_argument("--max-hour", type=int, default=30)
    parser.add_argument("--tag", default="", help="Optional output filename tag.")
    parser.add_argument("--dashboard-index", type=int, default=6)
    return parser.parse_args()


@contextmanager
def open_binary(path: pathlib.Path) -> Iterator[BinaryIO]:
    if path.suffix == ".zst":
        try:
            import zstandard as zstd
        except ImportError:
            executable = shutil.which("zstd")
            if executable is None:
                raise RuntimeError(
                    "Reading .zst files requires the zstandard module or zstd executable."
                )
            process = subprocess.Popen(
                [executable, "-dc", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if process.stdout is None:
                raise RuntimeError("Could not open zstd stdout.")
            try:
                yield process.stdout
            finally:
                process.stdout.close()
                stderr = process.stderr.read().decode("utf-8", errors="replace")
                return_code = process.wait()
                process.stderr.close()
                if return_code != 0:
                    raise RuntimeError(
                        f"zstd failed for {path} with exit code {return_code}: {stderr}"
                    )
        else:
            with path.open("rb") as raw:
                with zstd.ZstdDecompressor().stream_reader(raw) as stream:
                    yield stream
    elif path.suffix == ".gz":
        with gzip.open(path, "rb") as stream:
            yield stream
    else:
        with path.open("rb") as stream:
            yield stream


def read_network_links(network_path: pathlib.Path) -> list[str]:
    with open_binary(network_path) as stream:
        link_ids: list[str] = []
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag == "link":
                modes = element.attrib.get("modes", "")
                if not modes or CAR_MODE in modes.split(","):
                    link_ids.append(element.attrib["id"])
            element.clear()
    return link_ids


def count_hourly_car_link_entries(
    events_path: pathlib.Path,
    max_hour: int,
    allowed_link_ids: set[str],
) -> tuple[dict[str, Counter[int]], Counter[int], Counter[str]]:
    by_link: dict[str, Counter[int]] = defaultdict(Counter)
    by_hour: Counter[int] = Counter()
    vehicle_modes: dict[str, str] = {}
    event_counts: Counter[str] = Counter()

    with open_binary(events_path) as stream:
        text = io.TextIOWrapper(stream, encoding="utf-8")
        for line in text:
            if "<event " not in line:
                continue
            attrs = dict(ATTR_RE.findall(line))
            event_type = attrs.get("type", "")

            if event_type == "vehicle enters traffic":
                vehicle_id = attrs.get("vehicle")
                mode = attrs.get("networkMode") or attrs.get("networkmode")
                if vehicle_id and mode:
                    vehicle_modes[vehicle_id] = mode
                if mode != CAR_MODE:
                    continue
            elif event_type == "entered link":
                vehicle_id = attrs.get("vehicle")
                if not vehicle_id or vehicle_modes.get(vehicle_id) != CAR_MODE:
                    continue
            else:
                continue

            link_id = attrs.get("link")
            time = attrs.get("time")
            if not link_id or time is None:
                continue
            if link_id not in allowed_link_ids:
                event_counts["skipped_non_car_link"] += 1
                continue
            hour = int(float(time) // 3600)
            if 0 <= hour <= max_hour:
                by_link[link_id][hour] += 1
                by_hour[hour] += 1
                event_counts[event_type] += 1

    return by_link, by_hour, event_counts


def hour_label(hour: int) -> str:
    return f"{hour:02d}:00:00"


def write_hourly_csv(
    path: pathlib.Path,
    link_ids: list[str],
    by_link: dict[str, Counter[int]],
    hours: list[int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["link_id", *map(hour_label, hours), "daily_total"])
        for link_id in link_ids:
            counts = by_link.get(link_id, Counter())
            values = [counts.get(hour, 0) for hour in hours]
            writer.writerow([link_id, *values, sum(values)])


def write_hourly_summary(
    path: pathlib.Path,
    by_link: dict[str, Counter[int]],
    by_hour: Counter[int],
    hours: list[int],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["hour", "time", "total_link_entries", "active_links"],
        )
        writer.writeheader()
        for hour in hours:
            writer.writerow(
                {
                    "hour": hour,
                    "time": hour_label(hour),
                    "total_link_entries": by_hour.get(hour, 0),
                    "active_links": sum(
                        counts.get(hour, 0) > 0 for counts in by_link.values()
                    ),
                }
            )


def write_dashboard(
    path: pathlib.Path, default_hour: str, hourly_csv: str, summary_csv: str
) -> None:
    path.write_text(
        f"""header:
  title: Hong Kong hourly car traffic
  description: Hourly private-car link entries from the completed MATSim iteration 50 events.
layout:
  summary:
  - type: plotly
    title: Car link entries by hour
    datasets:
      hourly: analysis/traffic/{summary_csv}
    traces:
    - x: $hourly.time
      y: $hourly.total_link_entries
      type: bar
      name: Car link entries
    layout:
      xaxis:
        title: Hour
      yaxis:
        title: Link entries
  peak_map:
  - type: map
    title: Peak-hour car traffic ({default_hour})
    description: Link width and color show simulated hourly private-car volume.
    height: 12.0
    datasets:
      traffic: analysis/traffic/{hourly_csv}
    display:
      lineWidth:
        dataset: traffic
        columnName: "{default_hour}"
        join: link_id
        scaleFactor: 100.0
      lineColor:
        dataset: traffic
        columnName: "{default_hour}"
        join: link_id
        colorRamp:
          ramp: YlOrRd
          steps: 7
      fill: {{}}
      fillHeight: {{}}
      radius: {{}}
    shapes:
      join: id
      file: analysis/network/network.avro
  interactive:
  - type: links
    title: Interactive hourly link-volume map
    description: Use display settings to select any hour or daily_total.
    network: output_network.xml.zst
    projection: EPSG:32650
    datasets:
      csvFile: analysis/traffic/{hourly_csv}
    display:
      color:
        dataset: csvFile
        columnName: "{default_hour}"
        colorRamp:
          ramp: YlOrRd
          steps: 7
      width:
        dataset: csvFile
        columnName: "{default_hour}"
        scaleFactor: 100
""",
        encoding="utf-8",
    )


def write_standalone(
    path: pathlib.Path, default_hour: str, hourly_csv: str
) -> None:
    path.write_text(
        f"""title: Hong Kong hourly car traffic volume
description: Hourly private-car link entries from MATSim iteration 50.
network: output_network.xml.zst
projection: EPSG:32650
csvFile: analysis/traffic/{hourly_csv}
center: 114.17, 22.32
zoom: 10
display:
  color:
    dataset: csvFile
    columnName: "{default_hour}"
    colorRamp:
      ramp: YlOrRd
      steps: 7
  width:
    dataset: csvFile
    columnName: "{default_hour}"
    scaleFactor: 100
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    events_path = args.events or output_dir / "output_events.xml.zst"
    network_path = args.network or output_dir / "output_network.xml.zst"
    if not events_path.is_file():
        raise FileNotFoundError(events_path)
    if not network_path.is_file():
        raise FileNotFoundError(network_path)

    link_ids = read_network_links(network_path)
    by_link, by_hour, event_counts = count_hourly_car_link_entries(
        events_path, args.max_hour, set(link_ids)
    )
    hours = list(range(args.max_hour + 1))
    nonzero_hours = [hour for hour in hours if by_hour[hour] > 0]
    default_hour = (
        hour_label(max(nonzero_hours, key=by_hour.__getitem__))
        if nonzero_hours
        else "08:00:00"
    )

    traffic_dir = output_dir / "analysis" / "traffic"
    suffix = f"_{args.tag}" if args.tag else ""
    hourly_name = f"traffic_volume_by_link_hour{suffix}.csv"
    summary_name = f"traffic_volume_by_hour_summary{suffix}.csv"
    write_hourly_csv(
        traffic_dir / hourly_name,
        link_ids,
        by_link,
        hours,
    )
    write_hourly_summary(
        traffic_dir / summary_name,
        by_link,
        by_hour,
        hours,
    )
    write_dashboard(
        output_dir / f"dashboard-{args.dashboard_index}.yaml",
        default_hour,
        hourly_name,
        summary_name,
    )
    write_standalone(
        output_dir / f"viz-links-hong-kong-hourly-traffic{suffix}.yaml",
        default_hour,
        hourly_name,
    )

    print(f"network_car_links={len(link_ids)}")
    print(f"counted_car_links={len(by_link)}")
    print(f"peak_hour={default_hour}")
    print(f"peak_link_entries={by_hour[int(default_hour[:2])]}")
    print(f"event_counts={dict(event_counts)}")


if __name__ == "__main__":
    main()
