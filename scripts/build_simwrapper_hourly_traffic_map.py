"""Build SimWrapper hourly traffic volume maps from MATSim events.

The generated CSV follows SimWrapper's link-plot convention: the first column is
the MATSim link id and subsequent columns are hourly values. SimWrapper can then
switch the displayed width/color column to inspect traffic volume over time.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import pathlib
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import zstandard as zstd


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "output-fuzhou-50"
EVENT_TYPES_TO_COUNT = {"entered link", "vehicle enters traffic"}
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create SimWrapper hourly traffic map inputs.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="MATSim output directory.")
    parser.add_argument("--events", default=None, help="Events file. Default: output_events.xml.zst in output-dir.")
    parser.add_argument("--network", default=None, help="Network file. Default: output_network.xml.zst in output-dir.")
    parser.add_argument("--max-hour", type=int, default=30, help="Maximum hour column to write, inclusive lower bound.")
    return parser.parse_args()


def open_text(path: pathlib.Path):
    if path.suffix == ".zst":
        dctx = zstd.ZstdDecompressor()
        raw = path.open("rb")
        stream = dctx.stream_reader(raw)
        return raw, stream, stream
    if path.suffix == ".gz":
        raw = gzip.open(path, "rb")
        return raw, raw, raw
    raw = path.open("rb")
    return raw, raw, raw


def read_network_links(network_path: pathlib.Path) -> list[str]:
    handles = open_text(network_path)
    raw_handle, stream_handle, readable = handles
    try:
        link_ids: list[str] = []
        for event, elem in ET.iterparse(readable, events=("end",)):
            if elem.tag == "link":
                link_ids.append(elem.attrib["id"])
                elem.clear()
        return link_ids
    finally:
        stream_handle.close()
        raw_handle.close()


def count_hourly_link_entries(events_path: pathlib.Path, max_hour: int) -> tuple[dict[str, Counter[int]], Counter[int]]:
    by_link: dict[str, Counter[int]] = defaultdict(Counter)
    by_hour: Counter[int] = Counter()

    dctx = zstd.ZstdDecompressor()
    with events_path.open("rb") as raw, dctx.stream_reader(raw) as stream:
        import io

        text = io.TextIOWrapper(stream, encoding="utf-8")
        for line in text:
            if "<event " not in line:
                continue
            attrs = dict(ATTR_RE.findall(line))
            event_type = attrs.get("type")
            if event_type not in EVENT_TYPES_TO_COUNT:
                continue
            link_id = attrs.get("link")
            if not link_id:
                continue
            hour = int(float(attrs["time"]) // 3600)
            if 0 <= hour <= max_hour:
                by_link[link_id][hour] += 1
                by_hour[hour] += 1

    return by_link, by_hour


def hour_label(hour: int) -> str:
    return f"{hour:02d}:00:00"


def write_hourly_csv(path: pathlib.Path, link_ids: list[str], by_link: dict[str, Counter[int]], hours: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["link_id", *[hour_label(hour) for hour in hours], "daily_total"])
        for link_id in link_ids:
            counts = by_link.get(link_id, Counter())
            values = [counts.get(hour, 0) for hour in hours]
            writer.writerow([link_id, *values, sum(values)])


def write_hourly_summary(path: pathlib.Path, by_link: dict[str, Counter[int]], by_hour: Counter[int], hours: list[int]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hour", "time", "total_link_entries", "active_links"])
        writer.writeheader()
        for hour in hours:
            active_links = sum(1 for counts in by_link.values() if counts.get(hour, 0) > 0)
            writer.writerow(
                {
                    "hour": hour,
                    "time": hour_label(hour),
                    "total_link_entries": by_hour.get(hour, 0),
                    "active_links": active_links,
                }
            )


def write_standalone_yaml(path: pathlib.Path, csv_rel: str, default_hour: str) -> None:
    path.write_text(
        f"""title: Fuzhou hourly car traffic volume
description: Hourly link-entry volumes from output_events.xml.zst. Use the SimWrapper display panel to switch width/color columns by hour.
network: output_network.xml.zst
projection: EPSG:32650
csvFile: {csv_rel}
center: 119.31, 26.08
zoom: 11
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


def write_dashboard_yaml(path: pathlib.Path, default_hour: str) -> None:
    path.write_text(
        f"""header:
  title: Hourly car traffic map
  description: Link-entry traffic volume by hour from MATSim events. The maps below show selected hours; open viz-links-fuzhou-hourly-traffic.yaml to interactively switch all hour columns.
layout:
  summary:
  - type: plotly
    title: Total link entries by hour
    description: Counts vehicle enters traffic + entered link events.
    datasets:
      hourly: analysis/traffic/traffic_volume_by_hour_summary.csv
    traces:
    - x: $hourly.time
      y: $hourly.total_link_entries
      type: bar
      name: link entries
    layout:
      xaxis:
        title: Hour
      yaxis:
        title: Link entries
  map_peak_morning:
  - type: map
    title: Morning traffic volume {default_hour}
    description: Link width/color = hourly link-entry volume.
    height: 12.0
    datasets:
      traffic: analysis/traffic/traffic_volume_by_link_hour.csv
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
  selected_hours:
  - type: links
    title: Interactive hourly link-volume map
    description: In the display settings, switch width/color column to any hour such as 07:00:00, 08:00:00, 17:00:00, daily_total.
    network: output_network.xml.zst
    projection: EPSG:32650
    datasets:
      csvFile: analysis/traffic/traffic_volume_by_link_hour.csv
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
    output_dir = pathlib.Path(args.output_dir)
    events_path = pathlib.Path(args.events) if args.events else output_dir / "output_events.xml.zst"
    network_path = pathlib.Path(args.network) if args.network else output_dir / "output_network.xml.zst"

    if not events_path.exists():
        raise FileNotFoundError(events_path)
    if not network_path.exists():
        raise FileNotFoundError(network_path)

    link_ids = read_network_links(network_path)
    by_link, by_hour = count_hourly_link_entries(events_path, args.max_hour)
    hours = list(range(0, args.max_hour + 1))
    nonzero_hours = [hour for hour in hours if by_hour.get(hour, 0) > 0]
    default_hour = hour_label(max(nonzero_hours, key=lambda hour: by_hour[hour])) if nonzero_hours else "08:00:00"

    traffic_dir = output_dir / "analysis" / "traffic"
    hourly_csv = traffic_dir / "traffic_volume_by_link_hour.csv"
    summary_csv = traffic_dir / "traffic_volume_by_hour_summary.csv"
    write_hourly_csv(hourly_csv, link_ids, by_link, hours)
    write_hourly_summary(summary_csv, by_link, by_hour, hours)

    write_standalone_yaml(output_dir / "viz-links-fuzhou-hourly-traffic.yaml", "analysis/traffic/traffic_volume_by_link_hour.csv", default_hour)
    write_dashboard_yaml(output_dir / "dashboard-6.yaml", default_hour)

    print(f"links={len(link_ids)}")
    print(f"counted_links={len(by_link)}")
    print(f"nonzero_hours={','.join(hour_label(hour) for hour in nonzero_hours)}")
    print(f"peak_hour={default_hour} total_entries={by_hour.get(int(default_hour[:2]), 0)}")
    print(f"wrote={hourly_csv}")
    print(f"wrote={summary_csv}")
    print(f"wrote={output_dir / 'dashboard-6.yaml'}")
    print(f"wrote={output_dir / 'viz-links-fuzhou-hourly-traffic.yaml'}")


if __name__ == "__main__":
    main()
