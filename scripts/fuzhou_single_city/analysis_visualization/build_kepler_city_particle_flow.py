"""Build an animated Kepler.gl Trips map from MATSim network events.

The output is a standalone Kepler.gl HTML file plus per-mode GeoJSON files.
Vehicle trajectories follow the simulated MATSim link sequence.  To keep the
browser responsive, trips are deterministically sampled and their paths are
simplified while preserving simulation timestamps.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import pathlib
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

import zstandard as zstd
from pyproj import Transformer


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / (
    "output-fuzhou-transit-mode-choice-2pct-waitpenalty-"
    "metroprefer-from-cont20-reroute50"
)
DEFAULT_TEMPLATE = (
    PROJECT_ROOT
    / ".tools"
    / "keplergl-src"
    / "keplergl-0.3.7"
    / "keplergl"
    / "static"
    / "keplergl.html"
)
BASE_EPOCH_S = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
MODES = ("car", "bus", "metro")
MODE_COLORS = {
    "car": [0, 220, 255],
    "bus": [255, 145, 40],
    "metro": [40, 255, 135],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Kepler.gl animated particle-flow map from MATSim events."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--events", default=None)
    parser.add_argument("--network", default=None)
    parser.add_argument("--transit-vehicles", default=None)
    parser.add_argument("--kepler-template", default=str(DEFAULT_TEMPLATE))
    parser.add_argument("--start-hour", type=float, default=5.0)
    parser.add_argument("--end-hour", type=float, default=24.0)
    parser.add_argument("--car-trips", type=int, default=2400)
    parser.add_argument("--bus-trips", type=int, default=1200)
    parser.add_argument("--metro-trips", type=int, default=400)
    parser.add_argument("--simplify-tolerance-m", type=float, default=18.0)
    parser.add_argument("--max-points-per-trip", type=int, default=140)
    parser.add_argument("--trail-length-s", type=int, default=480)
    parser.add_argument(
        "--html-name", default="kepler-fuzhou-city-particle-flow.html"
    )
    return parser.parse_args()


def open_binary(path: pathlib.Path):
    if path.suffix == ".zst":
        raw = path.open("rb")
        stream = zstd.ZstdDecompressor().stream_reader(raw)
        return raw, stream
    if path.suffix == ".gz":
        stream = gzip.open(path, "rb")
        return stream, stream
    stream = path.open("rb")
    return stream, stream


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass(frozen=True)
class Link:
    from_node: str
    to_node: str


@dataclass
class ActiveTrip:
    vehicle_id: str
    mode: str
    start_s: float
    current_link: str
    sample_key: int
    points: list[tuple[float, float, float, float, float]] = field(default_factory=list)


def read_network(
    network_path: pathlib.Path,
) -> tuple[dict[str, tuple[float, float, float, float]], dict[str, Link]]:
    raw, stream = open_binary(network_path)
    nodes_xy: dict[str, tuple[float, float]] = {}
    links: dict[str, Link] = {}
    try:
        for event, elem in ET.iterparse(stream, events=("end",)):
            name = local_name(elem.tag)
            if name == "node":
                nodes_xy[elem.attrib["id"]] = (
                    float(elem.attrib["x"]),
                    float(elem.attrib["y"]),
                )
            elif name == "link":
                links[elem.attrib["id"]] = Link(
                    from_node=elem.attrib["from"], to_node=elem.attrib["to"]
                )
            elem.clear()
    finally:
        stream.close()
        if raw is not stream:
            raw.close()

    transformer = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True)
    nodes: dict[str, tuple[float, float, float, float]] = {}
    for node_id, (x, y) in nodes_xy.items():
        lon, lat = transformer.transform(x, y)
        nodes[node_id] = (x, y, lon, lat)
    return nodes, links


def read_transit_vehicle_modes(path: pathlib.Path) -> dict[str, str]:
    raw, stream = open_binary(path)
    modes: dict[str, str] = {}
    try:
        for event, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) != "vehicle":
                elem.clear()
                continue
            vehicle_id = elem.attrib.get("id", "")
            type_id = elem.attrib.get("type", "").lower()
            combined = f"{vehicle_id.lower()} {type_id}"
            if "metro" in combined or "rail" in combined:
                modes[vehicle_id] = "metro"
            else:
                modes[vehicle_id] = "bus"
            elem.clear()
    finally:
        stream.close()
        if raw is not stream:
            raw.close()
    return modes


def stable_u64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def classify_mode(vehicle_id: str, transit_modes: dict[str, str]) -> str:
    mode = transit_modes.get(vehicle_id)
    if mode:
        return mode
    lowered = vehicle_id.lower()
    if "metro" in lowered:
        return "metro"
    if lowered.startswith(("bus_vehicle_", "optveh_bus_", "pt_bus_", "pt_optveh_bus_")):
        return "bus"
    return "car"


def iter_event_attributes(events_path: pathlib.Path):
    raw, stream = open_binary(events_path)
    try:
        text = io.TextIOWrapper(stream, encoding="utf-8")
        for line in text:
            if "<event " in line:
                yield dict(ATTR_RE.findall(line))
    finally:
        stream.close()
        if raw is not stream:
            raw.close()


def count_vehicle_trips(
    events_path: pathlib.Path,
    transit_modes: dict[str, str],
    start_s: float,
    end_s: float,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for attrs in iter_event_attributes(events_path):
        if attrs.get("type") != "vehicle enters traffic":
            continue
        time_s = float(attrs.get("time", "-1"))
        if not start_s <= time_s < end_s:
            continue
        vehicle_id = attrs.get("vehicle", "")
        if vehicle_id:
            counts[classify_mode(vehicle_id, transit_modes)] += 1
    return counts


def selection_thresholds(counts: Counter[str], quotas: dict[str, int]) -> dict[str, int]:
    max_u64 = (1 << 64) - 1
    thresholds: dict[str, int] = {}
    for mode in MODES:
        count = counts.get(mode, 0)
        if count <= 0:
            thresholds[mode] = 0
            continue
        probability = min(1.0, quotas[mode] * 1.25 / count)
        thresholds[mode] = int(max_u64 * probability)
    return thresholds


def append_node(
    trip: ActiveTrip,
    node_id: str,
    time_s: float,
    nodes: dict[str, tuple[float, float, float, float]],
) -> None:
    node = nodes.get(node_id)
    if node is None:
        return
    x, y, lon, lat = node
    if trip.points:
        last = trip.points[-1]
        if abs(last[0] - x) < 0.01 and abs(last[1] - y) < 0.01:
            if time_s > last[4]:
                trip.points[-1] = (x, y, lon, lat, time_s)
            return
        if time_s <= last[4]:
            time_s = last[4] + 0.001
    trip.points.append((x, y, lon, lat, time_s))


def perpendicular_distance(
    point: tuple[float, float, float, float, float],
    start: tuple[float, float, float, float, float],
    end: tuple[float, float, float, float, float],
) -> float:
    px, py = point[0], point[1]
    x1, y1 = start[0], start[1]
    x2, y2 = end[0], end[1]
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    qx, qy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - qx, py - qy)


def simplify_rdp(
    points: list[tuple[float, float, float, float, float]], tolerance_m: float
) -> list[tuple[float, float, float, float, float]]:
    if len(points) <= 2 or tolerance_m <= 0:
        return points
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        best_index = -1
        best_distance = -1.0
        for index in range(start + 1, end):
            distance = perpendicular_distance(points[index], points[start], points[end])
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index >= 0 and best_distance > tolerance_m:
            keep.add(best_index)
            stack.append((start, best_index))
            stack.append((best_index, end))
    return [points[index] for index in sorted(keep)]


def cap_points(
    points: list[tuple[float, float, float, float, float]], max_points: int
) -> list[tuple[float, float, float, float, float]]:
    if len(points) <= max_points:
        return points
    indices = {
        round(index * (len(points) - 1) / (max_points - 1))
        for index in range(max_points)
    }
    return [points[index] for index in sorted(indices)]


def path_length_m(points: list[tuple[float, float, float, float, float]]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(points, points[1:])
    )


def hhmmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def feature_from_trip(
    trip: ActiveTrip,
    tolerance_m: float,
    max_points: int,
) -> dict | None:
    points = cap_points(simplify_rdp(trip.points, tolerance_m), max_points)
    if len(points) < 2:
        return None
    distance_m = path_length_m(points)
    duration_s = points[-1][4] - points[0][4]
    if distance_m < 100 or duration_s <= 1:
        return None
    coordinates = [
        [round(point[2], 6), round(point[3], 6), 0, BASE_EPOCH_S + round(point[4], 3)]
        for point in points
    ]
    return {
        "type": "Feature",
        "properties": {
            "vehicle_id": trip.vehicle_id,
            "mode": trip.mode,
            "start_time": hhmmss(points[0][4]),
            "end_time": hhmmss(points[-1][4]),
            "duration_min": round(duration_s / 60.0, 2),
            "distance_km": round(distance_m / 1000.0, 2),
            "points": len(points),
            "sample_key": trip.sample_key,
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def build_sampled_trajectories(
    events_path: pathlib.Path,
    transit_modes: dict[str, str],
    nodes: dict[str, tuple[float, float, float, float]],
    links: dict[str, Link],
    thresholds: dict[str, int],
    quotas: dict[str, int],
    start_s: float,
    end_s: float,
    tolerance_m: float,
    max_points: int,
) -> tuple[dict[str, list[dict]], Counter[str]]:
    active: dict[str, ActiveTrip] = {}
    candidates: dict[str, list[dict]] = {mode: [] for mode in MODES}
    dropped: Counter[str] = Counter()

    def finalize(vehicle_id: str) -> None:
        trip = active.pop(vehicle_id, None)
        if trip is None:
            return
        feature = feature_from_trip(trip, tolerance_m, max_points)
        if feature is None:
            dropped[f"{trip.mode}_short_or_invalid"] += 1
            return
        candidates[trip.mode].append(feature)

    for attrs in iter_event_attributes(events_path):
        event_type = attrs.get("type")
        if event_type not in {
            "vehicle enters traffic",
            "entered link",
            "left link",
            "vehicle leaves traffic",
        }:
            continue
        vehicle_id = attrs.get("vehicle", "")
        if not vehicle_id:
            continue
        time_s = float(attrs.get("time", "-1"))

        if event_type == "vehicle enters traffic":
            if vehicle_id in active:
                finalize(vehicle_id)
            if not start_s <= time_s < end_s:
                continue
            mode = classify_mode(vehicle_id, transit_modes)
            sample_key = stable_u64(f"{vehicle_id}|{time_s:.3f}")
            if sample_key > thresholds.get(mode, 0):
                continue
            link_id = attrs.get("link", "")
            link = links.get(link_id)
            if link is None:
                dropped[f"{mode}_missing_start_link"] += 1
                continue
            trip = ActiveTrip(vehicle_id, mode, time_s, link_id, sample_key)
            append_node(trip, link.from_node, time_s, nodes)
            active[vehicle_id] = trip
            continue

        trip = active.get(vehicle_id)
        if trip is None:
            continue
        link_id = attrs.get("link", trip.current_link)
        link = links.get(link_id)
        if link is None:
            dropped[f"{trip.mode}_missing_link"] += 1
            continue
        if event_type == "entered link":
            trip.current_link = link_id
            append_node(trip, link.from_node, time_s, nodes)
        elif event_type == "left link":
            trip.current_link = link_id
            append_node(trip, link.to_node, time_s, nodes)
        elif event_type == "vehicle leaves traffic":
            append_node(trip, link.to_node, time_s, nodes)
            finalize(vehicle_id)

    for vehicle_id in list(active):
        finalize(vehicle_id)

    selected: dict[str, list[dict]] = {}
    for mode in MODES:
        ordered = sorted(
            candidates[mode], key=lambda feature: feature["properties"]["sample_key"]
        )
        selected[mode] = ordered[: quotas[mode]]
        dropped[f"{mode}_over_quota"] = max(0, len(ordered) - quotas[mode])
        for feature in selected[mode]:
            feature["properties"].pop("sample_key", None)
    return selected, dropped


def write_geojsons(output_dir: pathlib.Path, features: dict[str, list[dict]]) -> dict[str, pathlib.Path]:
    analysis_dir = output_dir / "analysis" / "kepler"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, pathlib.Path] = {}
    for mode in MODES:
        collection = {"type": "FeatureCollection", "features": features[mode]}
        path = analysis_dir / f"urban_particle_flow_{mode}.geojson"
        path.write_text(
            json.dumps(collection, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        with path.open("rb") as source, gzip.open(f"{path}.gz", "wb", compresslevel=9) as target:
            shutil.copyfileobj(source, target)
        paths[mode] = path
    return paths


def trip_layer(mode: str, trail_length_s: int) -> dict:
    labels = {"car": "Car particles", "bus": "Bus particles", "metro": "Metro particles"}
    return {
        "id": f"matsim-{mode}-trips",
        "type": "trip",
        "config": {
            "dataId": f"matsim_{mode}_trips",
            "label": labels[mode],
            "color": MODE_COLORS[mode],
            "highlightColor": [255, 255, 255, 255],
            "columns": {"geojson": "_geojson"},
            "isVisible": True,
            "visConfig": {
                "opacity": 0.9,
                "thickness": 2.2 if mode == "car" else 3.0,
                "trailLength": trail_length_s,
                "colorRange": {
                    "name": f"{mode} color",
                    "type": "sequential",
                    "category": "Custom",
                    "colors": ["#00dcff", "#ff9128", "#28ff87"],
                },
            },
            "hidden": False,
            "textLabel": [],
        },
        "visualChannels": {
            "colorField": None,
            "colorScale": "quantile",
            "sizeField": None,
            "sizeScale": "linear",
        },
    }


def build_config(features: dict[str, list[dict]], start_s: float, trail_length_s: int) -> dict:
    tooltip_fields = [
        {"name": "mode", "format": None},
        {"name": "start_time", "format": None},
        {"name": "end_time", "format": None},
        {"name": "distance_km", "format": None},
        {"name": "duration_min", "format": None},
    ]
    return {
        "version": "v1",
        "config": {
            "visState": {
                "filters": [],
                "layers": [trip_layer(mode, trail_length_s) for mode in MODES if features[mode]],
                "interactionConfig": {
                    "tooltip": {
                        "fieldsToShow": {
                            f"matsim_{mode}_trips": tooltip_fields for mode in MODES
                        },
                        "compareMode": False,
                        "compareType": "absolute",
                        "enabled": True,
                    },
                    "brush": {"size": 0.5, "enabled": False},
                    "geocoder": {"enabled": False},
                    "coordinate": {"enabled": True},
                },
                "layerBlending": "additive",
                "splitMaps": [],
                "animationConfig": {
                    "currentTime": BASE_EPOCH_S + start_s,
                    "speed": 1,
                },
            },
            "mapState": {
                "bearing": 0,
                "dragRotate": True,
                "latitude": 26.0745,
                "longitude": 119.2965,
                "pitch": 38,
                "zoom": 10.45,
                "isSplit": False,
            },
            "mapStyle": {
                "styleType": "dark-matter",
                "topLayerGroups": {},
                "visibleLayerGroups": {
                    "label": True,
                    "road": True,
                    "border": False,
                    "building": True,
                    "water": True,
                    "land": True,
                    "3d building": False,
                },
                "threeDBuildingColor": [9.665468314072013, 17.18305478057247, 31.1442867897876],
                "mapStyles": {},
            },
        },
    }


def build_standalone_html(
    template_path: pathlib.Path,
    destination: pathlib.Path,
    data: dict[str, dict],
    config: dict,
) -> None:
    template = template_path.read_text(encoding="utf-8")
    responsive_css = (
        "<style>"
        "html,body{width:100%;height:100%;overflow:hidden;}"
        "#kepler-gl__map{width:100vw!important;height:100vh!important;}"
        "</style>"
    )
    template = template.replace("</head>", responsive_css + "</head>", 1)
    body_index = template.find("<body>")
    if body_index < 0:
        raise ValueError(f"Kepler template has no <body>: {template_path}")
    payload = json.dumps(
        {
            "config": config,
            "data": data,
            "options": {"readOnly": False, "centerMap": False},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    command = f"<body><script>window.__keplerglDataConfig={payload};</script>"
    html = template[:body_index] + command + template[body_index + len("<body>") :]
    html = html.replace("<title>Kepler.gl</title>", "<title>Fuzhou MATSim City Particle Flow</title>", 1)
    destination.write_text(html, encoding="utf-8")


def main() -> None:
    args = parse_args()
    output_dir = pathlib.Path(args.output_dir).resolve()
    events_path = pathlib.Path(args.events).resolve() if args.events else output_dir / "output_events.xml.zst"
    network_path = pathlib.Path(args.network).resolve() if args.network else output_dir / "output_network.xml.zst"
    transit_path = (
        pathlib.Path(args.transit_vehicles).resolve()
        if args.transit_vehicles
        else output_dir / "output_transitVehicles.xml.zst"
    )
    template_path = pathlib.Path(args.kepler_template).resolve()
    for required in (events_path, network_path, transit_path, template_path):
        if not required.exists():
            raise FileNotFoundError(required)

    start_s = args.start_hour * 3600.0
    end_s = args.end_hour * 3600.0
    quotas = {
        "car": args.car_trips,
        "bus": args.bus_trips,
        "metro": args.metro_trips,
    }

    print("Reading MATSim network...")
    nodes, links = read_network(network_path)
    transit_modes = read_transit_vehicle_modes(transit_path)
    print(f"nodes={len(nodes)} links={len(links)} transit_vehicles={len(transit_modes)}")

    print("Pass 1/2: counting vehicle trips...")
    counts = count_vehicle_trips(events_path, transit_modes, start_s, end_s)
    thresholds = selection_thresholds(counts, quotas)
    print("trip_counts=" + json.dumps(counts, ensure_ascii=False, sort_keys=True))

    print("Pass 2/2: reconstructing sampled link trajectories...")
    features, dropped = build_sampled_trajectories(
        events_path=events_path,
        transit_modes=transit_modes,
        nodes=nodes,
        links=links,
        thresholds=thresholds,
        quotas=quotas,
        start_s=start_s,
        end_s=end_s,
        tolerance_m=args.simplify_tolerance_m,
        max_points=args.max_points_per_trip,
    )

    geojson_paths = write_geojsons(output_dir, features)
    data = {
        f"matsim_{mode}_trips": json.loads(path.read_text(encoding="utf-8"))
        for mode, path in geojson_paths.items()
    }
    config = build_config(features, start_s, args.trail_length_s)
    html_path = output_dir / args.html_name
    build_standalone_html(template_path, html_path, data, config)

    selected_counts = {mode: len(features[mode]) for mode in MODES}
    point_counts = {
        mode: sum(len(feature["geometry"]["coordinates"]) for feature in features[mode])
        for mode in MODES
    }
    summary = {
        "source_output": str(output_dir),
        "events": str(events_path),
        "network": str(network_path),
        "time_window": {"start_hour": args.start_hour, "end_hour": args.end_hour},
        "base_timestamp_utc": datetime.fromtimestamp(BASE_EPOCH_S, tz=timezone.utc).isoformat(),
        "raw_vehicle_trip_counts": dict(counts),
        "requested_sample_quotas": quotas,
        "selected_trip_counts": selected_counts,
        "selected_path_point_counts": point_counts,
        "dropped": dict(dropped),
        "simplify_tolerance_m": args.simplify_tolerance_m,
        "max_points_per_trip": args.max_points_per_trip,
        "trail_length_s": args.trail_length_s,
        "outputs": {
            "html": str(html_path),
            **{f"{mode}_geojson": str(path) for mode, path in geojson_paths.items()},
        },
        "notes": [
            "Trajectories follow MATSim link enter/leave events.",
            "The visualization is a deterministic stratified sample for browser performance.",
            "Kepler.gl Trips coordinates are WGS84 [lon, lat, altitude, Unix timestamp].",
        ],
    }
    summary_path = output_dir / "analysis" / "kepler" / "urban_particle_flow_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("selected=" + json.dumps(selected_counts, ensure_ascii=False, sort_keys=True))
    print("points=" + json.dumps(point_counts, ensure_ascii=False, sort_keys=True))
    print(f"html={html_path}")
    print(f"summary={summary_path}")


if __name__ == "__main__":
    main()
