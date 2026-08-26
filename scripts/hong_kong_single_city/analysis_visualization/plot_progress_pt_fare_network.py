"""Plot actual iteration-49 PT itineraries and strict rule-based fares.

The main map aggregates completed experienced PT itineraries whose first
boarding lies in the Central--Admiralty source area.  Each itinerary is quoted
segment by segment with the same exact-key, no-fallback semantics as the Java
runtime fare catalog.  Unresolved segments remain unresolved and are excluded
from complete-fare map aggregation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import textwrap
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import zstandard as zstd
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch

from progress_report_figure_style import (
    PALETTE,
    add_method_note,
    apply_progress_report_style,
    clean_map_axis,
    save_figure,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = (
    ROOT
    / "runs/hongkong/outputs/progress_report_figures_20260824/source_data"
    / "pt_it49"
)
DEFAULT_FARES = ROOT / "data/transport_costs/hongkong/pt_fare_v1"
DEFAULT_BOUNDARY = (
    ROOT
    / "runs/hongkong/outputs/progress_report_figures_20260824/source_data"
    / "hong_kong_fixed_link_boundary.geojson"
)
DEFAULT_OUTPUT = ROOT / "runs/hongkong/outputs/progress_report_figures_20260824"

ORIGIN_X = 207_650.0
ORIGIN_Y = 2_466_800.0
ORIGIN_RADIUS_M = 1_200.0

EXPECTED_SHA256 = {
    "mtr_station_od_v1/mtr_station_od_fare_rules.parquet": "0829574983542c8178a562463d1711f93fe8381dfda7a7ad88bb7a8c7c2701fa",
    "mtr_station_od_v1/mtr_station_crosswalk.csv": "f566103c1529f18fe39f92e41601a1e77ba00e4b77d35fb5a5b8ff77ecaf7926",
    "light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet": "92596e56342eeffe5374aa4ed7dba9a5b57986ab3257623e64e04cb837a64004",
    "light_rail_station_od_v1/light_rail_stop_crosswalk.csv": "448f921cd1eac9338f883ef3f3d94ce2f04047ca3687f15a712d70b86e905942",
    "gmb_fare_v1/gmb_fare_rules.parquet": "edc794e0940985b64056041e1449d26a8bc3d3331f37df3475d04726c86e14f7",
    "gmb_fare_v1/gmb_stop_crosswalk.csv": "71ccdb344f0379f27dc315efbb527f7ea02c853afa7a166879ce956531d06b58",
    "ferry_fare_v1/ferry_fare_rules.parquet": "8d79774373f9de9b086382fce611a13750e63c664444fe7eb15555e44c6d189d",
    "ferry_fare_v1/ferry_stop_crosswalk.csv": "76cf3d2f0020f9cc78dff00e3acb26081f4a63017b8d52d1d1e5546fc31d3cfa",
    "bus_fare_v1/bus_fare_rules.parquet": "6a67270cc996dfc9217380e17cb1ed662daccd3f4c74fb52e766f321646237b4",
    "bus_scope_direction_audit_v1/bus_stop_crosswalk.csv": "3915dc5bbe724ba0527cb5faa4a8196e6724c8137038cdb817f00d1a5d7d12f5",
}

MODE_COLORS = {
    "train": PALETTE["blue"],
    "light_rail": PALETTE["purple"],
    "bus": PALETTE["brick"],
    "gmb": PALETTE["green"],
    "ferry": PALETTE["gold"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--fare-root", type=Path, default=DEFAULT_FARES)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-destinations", type=int, default=42)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_fare_sources(root: Path) -> None:
    for relative, expected in EXPECTED_SHA256.items():
        path = root / relative
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"Strict PT fare source hash mismatch: {relative}: {actual}")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_schedule(path: Path) -> tuple[dict[tuple[str, str], str], dict[str, dict[str, object]]]:
    route_modes: dict[tuple[str, str], str] = {}
    stops: dict[str, dict[str, object]] = {}
    current_line = ""
    current_route = ""
    with path.open("rb") as raw:
        with zstd.ZstdDecompressor().stream_reader(raw) as reader:
            for event, elem in ET.iterparse(reader, events=("start", "end")):
                tag = local_name(elem.tag)
                if event == "start" and tag == "transitLine":
                    current_line = elem.attrib["id"]
                elif event == "start" and tag == "transitRoute":
                    current_route = elem.attrib["id"]
                elif event == "end" and tag == "transportMode" and current_line and current_route:
                    route_modes[(current_line, current_route)] = (elem.text or "").strip()
                elif event == "end" and tag == "stopFacility":
                    stops[elem.attrib["id"]] = {
                        "x": float(elem.attrib["x"]),
                        "y": float(elem.attrib["y"]),
                        "name": elem.attrib.get("name", elem.attrib["id"]),
                    }
                    elem.clear()
                elif event == "end" and tag == "transitRoute":
                    current_route = ""
                    elem.clear()
                elif event == "end" and tag == "transitLine":
                    current_line = ""
                    elem.clear()
    return route_modes, stops


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class StrictFareCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.crosswalks: dict[str, dict[str, str]] = {}
        self.rules: dict[str, dict[tuple[str, ...], tuple[float | None, str]]] = {}
        self._load_crosswalks()
        self._load_rules()

    def _load_station_crosswalk(
        self, relative: str, official_column: str, facilities_column: str, in_matrix_column: str
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in read_csv(self.root / relative):
            if row["mapping_status"] != "exact" or row[in_matrix_column] != "True":
                continue
            for facility in json.loads(row[facilities_column]):
                result[facility] = row[official_column]
        return result

    def _load_one_facility_crosswalk(self, relative: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in read_csv(self.root / relative):
            if row["mapping_status"] == "exact" and row["matsim_stop_facility_id"] and row["official_stop_id"]:
                result[row["matsim_stop_facility_id"]] = row["official_stop_id"]
        return result

    def _load_crosswalks(self) -> None:
        self.crosswalks["train"] = self._load_station_crosswalk(
            "mtr_station_od_v1/mtr_station_crosswalk.csv",
            "station_id", "schedule_facility_ids_json", "in_domestic_fare_matrix",
        )
        self.crosswalks["light_rail"] = self._load_station_crosswalk(
            "light_rail_station_od_v1/light_rail_stop_crosswalk.csv",
            "stop_id", "schedule_facility_ids_json", "in_fare_matrix",
        )
        self.crosswalks["gmb"] = self._load_one_facility_crosswalk("gmb_fare_v1/gmb_stop_crosswalk.csv")
        self.crosswalks["ferry"] = self._load_one_facility_crosswalk("ferry_fare_v1/ferry_stop_crosswalk.csv")
        self.crosswalks["bus"] = self._load_one_facility_crosswalk("bus_scope_direction_audit_v1/bus_stop_crosswalk.csv")

    @staticmethod
    def _available_cost(row: pd.Series, column: str) -> tuple[float | None, str]:
        status = str(row["record_status"])
        value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
        if status == "available" and pd.notna(value):
            return float(value), "resolved"
        reason = str(row.get("unresolved_reason", "canonical_rule_unresolved"))
        return None, reason if reason and reason != "nan" else "canonical_rule_unresolved"

    def _load_rules(self) -> None:
        mtr = pd.read_parquet(self.root / "mtr_station_od_v1/mtr_station_od_fare_rules.parquet")
        mtr = mtr[mtr["fare_network_scope"].eq("domestic_mtr_station_od")]
        self.rules["train"] = {
            (str(row.boarding_station_id), str(row.alighting_station_id)): self._available_cost(row, "adult_octopus_fare_hkd")
            for _, row in mtr.iterrows()
        }
        light = pd.read_parquet(
            self.root / "light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet"
        )
        light = light[light["fare_network_scope"].eq("light_rail_station_od")]
        self.rules["light_rail"] = {
            (str(row.boarding_stop_id), str(row.alighting_stop_id)): self._available_cost(row, "adult_octopus_fare_hkd")
            for _, row in light.iterrows()
        }
        for mode, relative in (
            ("gmb", "gmb_fare_v1/gmb_fare_rules.parquet"),
            ("ferry", "ferry_fare_v1/ferry_fare_rules.parquet"),
            ("bus", "bus_fare_v1/bus_fare_rules.parquet"),
        ):
            frame = pd.read_parquet(self.root / relative)
            self.rules[mode] = {
                (
                    str(row.matsim_line_id), str(row.matsim_route_id),
                    str(row.boarding_stop_id), str(row.alighting_stop_id),
                ): self._available_cost(row, "published_fare_hkd")
                for _, row in frame.iterrows()
            }

    def quote(
        self, mode: str, line: str, route: str, boarding_facility: str, alighting_facility: str
    ) -> tuple[float | None, str, str, str]:
        if mode not in self.crosswalks:
            return None, "actual_transport_mode_not_in_stage7_layers", "", ""
        crosswalk = self.crosswalks[mode]
        boarding = crosswalk.get(boarding_facility, "")
        alighting = crosswalk.get(alighting_facility, "")
        if not boarding:
            return None, "boarding_facility_has_no_exact_canonical_crosswalk", boarding, alighting
        if not alighting:
            return None, "alighting_facility_has_no_exact_canonical_crosswalk", boarding, alighting
        key = (boarding, alighting) if mode in {"train", "light_rail"} else (line, route, boarding, alighting)
        match = self.rules[mode].get(key)
        if match is None:
            return None, f"{mode}_exact_ordered_od_rule_missing", boarding, alighting
        return match[0], match[1], boarding, alighting


def load_experienced_pt_legs(path: Path, route_modes: dict[tuple[str, str], str]) -> pd.DataFrame:
    columns = [
        "person", "trip_id", "dep_time", "trav_time", "distance", "mode",
        "start_x", "start_y", "end_x", "end_y", "access_stop_id", "egress_stop_id",
        "transit_line", "transit_route", "vehicle_id",
    ]
    frame = pd.read_csv(path, sep=";", usecols=columns, dtype=str)
    frame = frame.loc[frame["mode"].eq("pt")].copy()
    for column in ("start_x", "start_y", "end_x", "end_y", "distance"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["actual_mode"] = [
        route_modes.get((line, route), "")
        for line, route in zip(frame["transit_line"], frame["transit_route"], strict=True)
    ]
    frame["segment_sequence"] = frame.groupby("trip_id", sort=False).cumcount()
    return frame


def quote_legs(frame: pd.DataFrame, catalog: StrictFareCatalog) -> pd.DataFrame:
    quotes = [
        catalog.quote(
            str(row.actual_mode), str(row.transit_line), str(row.transit_route),
            str(row.access_stop_id), str(row.egress_stop_id),
        )
        for row in frame.itertuples(index=False)
    ]
    result = frame.copy()
    result["fare_hkd"] = [quote[0] for quote in quotes]
    result["fare_status"] = ["resolved" if quote[0] is not None else quote[1] for quote in quotes]
    result["boarding_official_id"] = [quote[2] for quote in quotes]
    result["alighting_official_id"] = [quote[3] for quote in quotes]
    result["fare_resolved"] = result["fare_hkd"].notna()
    return result


def clean_stop_name(value: str, width: int = 22) -> str:
    name = value.split(" (")[0].strip()
    return textwrap.shorten(name, width=width, placeholder="…")


def build_itineraries(
    legs: pd.DataFrame, stops: dict[str, dict[str, object]]
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    first = legs.groupby("trip_id", sort=False).first()
    first["origin_distance_m"] = np.hypot(first["start_x"] - ORIGIN_X, first["start_y"] - ORIGIN_Y)
    origin_trip_ids = set(first.index[first["origin_distance_m"].le(ORIGIN_RADIUS_M)])
    subset = legs.loc[legs["trip_id"].isin(origin_trip_ids)].copy()
    groups: dict[str, pd.DataFrame] = {}
    records: list[dict[str, object]] = []
    for trip_id, group in subset.groupby("trip_id", sort=False):
        ordered = group.sort_values("segment_sequence").copy()
        groups[trip_id] = ordered
        last = ordered.iloc[-1]
        complete = bool(ordered["fare_resolved"].all())
        official = str(last["alighting_official_id"])
        mode = str(last["actual_mode"])
        destination_key = f"{mode}:{official}" if official else f"unresolved:{last['egress_stop_id']}"
        stop = stops.get(str(last["egress_stop_id"]), {})
        records.append(
            {
                "trip_id": trip_id,
                "person": ordered.iloc[0]["person"],
                "departure_time": ordered.iloc[0]["dep_time"],
                "segment_count": len(ordered),
                "modes": tuple(ordered["actual_mode"]),
                "complete_fare": complete,
                "fare_hkd": float(ordered["fare_hkd"].sum()) if complete else np.nan,
                "destination_key": destination_key,
                "destination_mode": mode,
                "destination_official_id": official,
                "destination_facility": str(last["egress_stop_id"]),
                "destination_name": str(stop.get("name", last["egress_stop_id"])),
                "end_x": float(last["end_x"]),
                "end_y": float(last["end_y"]),
            }
        )
    return pd.DataFrame.from_records(records), groups


def select_examples(itineraries: pd.DataFrame, groups: dict[str, pd.DataFrame]) -> list[str]:
    resolved = itineraries[itineraries["complete_fare"]].copy()
    resolved["unique_modes"] = resolved["modes"].apply(lambda modes: len(set(modes)))
    categories = [
        ("MTR itinerary", lambda row: row.segment_count == 1 and row.modes == ("train",)),
        ("Bus itinerary", lambda row: row.segment_count == 1 and row.modes == ("bus",)),
        ("Ferry itinerary", lambda row: "ferry" in row.modes),
        ("Transfer itinerary", lambda row: row.segment_count >= 2),
    ]
    selected: list[str] = []
    for _, predicate in categories:
        candidates = resolved[resolved.apply(predicate, axis=1) & ~resolved["trip_id"].isin(selected)]
        if candidates.empty:
            continue
        destination_counts = candidates["destination_key"].value_counts()
        target_destination = destination_counts.index[0]
        candidates = candidates[candidates["destination_key"].eq(target_destination)].copy()
        median = candidates["fare_hkd"].median()
        candidates["distance_to_median"] = (candidates["fare_hkd"] - median).abs()
        selected.append(str(candidates.sort_values(["distance_to_median", "trip_id"]).iloc[0]["trip_id"]))
    return selected[:4]


def mode_display(mode: str) -> str:
    return {"train": "MTR", "light_rail": "LRT", "gmb": "GMB", "ferry": "Ferry", "bus": "Bus"}.get(mode, mode)


def short_line_id(line: str) -> str:
    for prefix in ("line_mtr_", "line_bus_", "line_gmb_", "line_ferry_"):
        if line.startswith(prefix):
            return line[len(prefix):]
    return line


def draw_itinerary_lane(
    ax, y: float, height: float, trip: pd.Series, legs: pd.DataFrame, stops: dict[str, dict[str, object]]
) -> None:
    legs = legs.sort_values("segment_sequence")
    n = len(legs)
    x_positions = np.linspace(0.08, 0.93, n + 1)
    ax.text(
        0.02, y + height * 0.82,
        f"{trip['departure_time']}  ·  {n} segment{'s' if n != 1 else ''}  ·  HK${trip['fare_hkd']:.1f}",
        transform=ax.transAxes, ha="left", va="top", fontsize=8.6, color=PALETTE["text"],
    )
    names = []
    first = legs.iloc[0]
    names.append(str(stops.get(str(first["access_stop_id"]), {}).get("name", first["access_stop_id"])))
    for row in legs.itertuples(index=False):
        names.append(str(stops.get(str(row.egress_stop_id), {}).get("name", row.egress_stop_id)))
    baseline = y + height * 0.45
    for index, row in enumerate(legs.itertuples(index=False)):
        x0, x1 = x_positions[index], x_positions[index + 1]
        color = MODE_COLORS.get(str(row.actual_mode), PALETTE["muted"])
        ax.plot([x0, x1], [baseline, baseline], transform=ax.transAxes, color=color, linewidth=3.0, solid_capstyle="round", zorder=2)
        ax.text(
            (x0 + x1) / 2, baseline + height * 0.13,
            f"{mode_display(str(row.actual_mode))} {short_line_id(str(row.transit_line))}\nHK${float(row.fare_hkd):.1f}",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=7.0, color=PALETTE["muted"],
        )
    for index, (x, name) in enumerate(zip(x_positions, names, strict=True)):
        color = PALETTE["blue"] if index == 0 else PALETTE["brick"]
        ax.scatter([x], [baseline], transform=ax.transAxes, s=32, color=color, edgecolor="white", linewidth=0.7, zorder=3)
        ax.text(
            x, baseline - height * 0.13, clean_stop_name(name, 18),
            transform=ax.transAxes, ha="center", va="top", fontsize=6.9, color=PALETTE["text"],
        )


def main() -> int:
    args = parse_args()
    verify_fare_sources(args.fare_root)
    route_modes, stops = parse_schedule(args.source_dir / "output_transitSchedule.xml.zst")
    legs = load_experienced_pt_legs(args.source_dir / "49.legs.csv.zst", route_modes)
    derived = args.output_dir / "source_data/pt_it49/figure_8_central_admiralty_quoted_legs.parquet"
    if derived.exists():
        quoted = pd.read_parquet(derived)
    else:
        first = legs.groupby("trip_id", sort=False).first()
        first["origin_distance_m"] = np.hypot(
            first["start_x"] - ORIGIN_X, first["start_y"] - ORIGIN_Y
        )
        source_trip_ids = set(first.index[first["origin_distance_m"].le(ORIGIN_RADIUS_M)])
        catalog = StrictFareCatalog(args.fare_root)
        quoted = quote_legs(legs.loc[legs["trip_id"].isin(source_trip_ids)].copy(), catalog)
    itineraries, groups = build_itineraries(quoted, stops)
    resolved = itineraries[itineraries["complete_fare"]].copy()
    if resolved.empty:
        raise ValueError("No Central--Admiralty iteration-49 PT itineraries have complete strict fares")

    destinations = (
        resolved.groupby("destination_key", as_index=False)
        .agg(
            trips=("trip_id", "size"),
            median_fare_hkd=("fare_hkd", "median"),
            total_fare_hkd=("fare_hkd", "sum"),
            destination_name=("destination_name", "first"),
            destination_mode=("destination_mode", "first"),
            end_x=("end_x", "median"),
            end_y=("end_y", "median"),
        )
        .sort_values("trips", ascending=False)
    )
    mapped = destinations.head(args.top_destinations).copy()
    examples = select_examples(itineraries, groups)

    boundary = gpd.read_file(args.boundary)
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:32650")
    elif str(boundary.crs).upper() != "EPSG:32650":
        boundary = boundary.to_crs("EPSG:32650")

    apply_progress_report_style()
    fig = plt.figure(figsize=(15.2, 10.2))
    grid = fig.add_gridspec(
        1, 2, width_ratios=(1.58, 1.0), left=0.035, right=0.98, top=0.875,
        bottom=0.09, wspace=0.06,
    )
    ax_map = fig.add_subplot(grid[0, 0])
    ax_detail = fig.add_subplot(grid[0, 1])
    fig.suptitle("Experienced public-transport fare network from Central–Admiralty", y=0.965)
    fig.text(
        0.5, 0.925,
        "Iteration 49 actual boardings and alightings; complete adult-reference fares quoted by exact route and ordered stop pair",
        ha="center", va="center", color=PALETTE["muted"], fontsize=10.5,
    )

    boundary.plot(ax=ax_map, facecolor=PALETTE["land"], edgecolor=PALETTE["boundary"], linewidth=0.65, zorder=0)
    fare_low, fare_high = np.quantile(mapped["median_fare_hkd"], [0.05, 0.95])
    if math.isclose(float(fare_low), float(fare_high)):
        fare_high = float(fare_low) + 1.0
    norm = Normalize(vmin=float(fare_low), vmax=float(fare_high), clip=True)
    cmap = LinearSegmentedColormap.from_list(
        "fare", [PALETTE["blue_light"], PALETTE["gold"], PALETTE["brick"]]
    )
    trip_min = max(1.0, float(mapped["trips"].min()))
    trip_max = max(trip_min + 1.0, float(mapped["trips"].max()))
    for rank, row in enumerate(mapped.itertuples(index=False)):
        width = 0.55 + 4.0 * math.sqrt((row.trips - trip_min) / (trip_max - trip_min))
        radius = 0.03 * ((rank % 7) - 3)
        arrow = FancyArrowPatch(
            (ORIGIN_X, ORIGIN_Y), (row.end_x, row.end_y),
            arrowstyle="-|>", mutation_scale=7.5, linewidth=width,
            color=cmap(norm(row.median_fare_hkd)), alpha=0.63,
            connectionstyle=f"arc3,rad={radius}", zorder=2,
        )
        ax_map.add_patch(arrow)
    node_sizes = 14 + 90 * np.sqrt(mapped["trips"] / mapped["trips"].max())
    ax_map.scatter(
        mapped["end_x"], mapped["end_y"], s=node_sizes,
        c=mapped["median_fare_hkd"], cmap=cmap, norm=norm,
        edgecolor="white", linewidth=0.6, zorder=4,
    )
    origin_circle = Circle(
        (ORIGIN_X, ORIGIN_Y), ORIGIN_RADIUS_M, facecolor=PALETTE["blue_light"],
        edgecolor=PALETTE["blue"], linewidth=1.0, alpha=0.24, zorder=1,
    )
    ax_map.add_patch(origin_circle)
    ax_map.scatter([ORIGIN_X], [ORIGIN_Y], s=118, color=PALETTE["blue"], edgecolor="white", linewidth=1.2, zorder=5)
    ax_map.annotate(
        "Central–Admiralty\n1.2 km source area", (ORIGIN_X, ORIGIN_Y), xytext=(10, -11),
        textcoords="offset points", fontsize=8.4, color=PALETTE["text"], ha="left", va="top", zorder=6,
    )
    for label_index, row in enumerate(mapped.head(7).itertuples(index=False)):
        x_offset = 4 if row.end_x >= ORIGIN_X else -4
        y_offset = 5 if label_index % 2 == 0 else -8
        ax_map.annotate(
            clean_stop_name(row.destination_name, 24), (row.end_x, row.end_y),
            xytext=(x_offset, y_offset), textcoords="offset points", fontsize=6.8,
            color=PALETTE["text"], ha="left" if x_offset > 0 else "right", zorder=6,
        )
    minx, miny, maxx, maxy = boundary.total_bounds
    ax_map.set_xlim(minx - 1200, maxx + 1200)
    ax_map.set_ylim(miny - 1200, maxy + 1200)
    clean_map_axis(ax_map)
    ax_map.set_title("A  Actual destination network", loc="left", fontsize=12.2, pad=6)

    scalar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    colorbar = fig.colorbar(scalar, ax=ax_map, orientation="horizontal", fraction=0.035, pad=0.015, shrink=0.50, anchor=(0.0, 0.5))
    colorbar.set_label("Median complete itinerary fare (HKD)", fontsize=8.2)
    colorbar.ax.tick_params(labelsize=7.5)
    q_counts = np.unique(np.maximum(1, np.round(np.quantile(mapped["trips"], [0.25, 0.65, 0.95])).astype(int)))
    width_handles = []
    for value in q_counts:
        width = 0.55 + 4.0 * math.sqrt((value - trip_min) / (trip_max - trip_min))
        width_handles.append(Line2D([], [], color=PALETTE["muted"], linewidth=width, label=f"{value:,} trips"))
    ax_map.legend(handles=width_handles, title="Flow width", loc="upper right", frameon=True, fontsize=8.0, title_fontsize=8.2)
    ax_map.text(
        0.016, 0.02,
        f"{len(itineraries):,} experienced PT itineraries start in the source area\n"
        f"{len(resolved):,} ({len(resolved) / len(itineraries):.1%}) have complete strict segment fares; "
        f"top {len(mapped)} destination stops shown",
        transform=ax_map.transAxes, ha="left", va="bottom", fontsize=8.2, color=PALETTE["text"],
        bbox=dict(facecolor="white", edgecolor=PALETTE["grid"], linewidth=0.6, alpha=0.93, boxstyle="square,pad=0.45"),
    )

    ax_detail.set_axis_off()
    ax_detail.set_xlim(0, 1)
    ax_detail.set_ylim(0, 1)
    ax_detail.set_title("B  Representative experienced itineraries", loc="left", fontsize=12.2, pad=6)
    ax_detail.text(
        0.02, 0.96,
        "Each lane is one actual iteration-49 passenger itinerary.\n"
        "Labels show the runtime transport mode, MATSim line identity, and exact segment fare.",
        transform=ax_detail.transAxes, ha="left", va="top", fontsize=8.7, color=PALETTE["muted"],
    )
    lane_height = 0.16
    lane_bottoms = [0.68, 0.49, 0.30, 0.11]
    for index, trip_id in enumerate(examples):
        trip = itineraries.set_index("trip_id").loc[trip_id]
        lane_bottom = lane_bottoms[index]
        draw_itinerary_lane(ax_detail, lane_bottom, lane_height, trip, groups[trip_id], stops)
        if index < len(examples) - 1:
            ax_detail.plot(
                [0.02, 0.98], [lane_bottom - 0.035] * 2,
                transform=ax_detail.transAxes, color=PALETTE["grid"], linewidth=0.6,
            )
    mode_handles = [
        Line2D([], [], color=color, linewidth=3, label=mode_display(mode))
        for mode, color in MODE_COLORS.items()
        if mode in set(quoted["actual_mode"])
    ]
    ax_detail.legend(handles=mode_handles, loc="lower left", ncol=3, frameon=True, fontsize=7.7)
    unresolved_trip_ids = set(itineraries.loc[~itineraries["complete_fare"], "trip_id"])
    unresolved_reasons = Counter(
        quoted.loc[
            quoted["trip_id"].isin(unresolved_trip_ids) & ~quoted["fare_resolved"],
            "fare_status",
        ]
    )
    if unresolved_reasons:
        top_reason, top_count = unresolved_reasons.most_common(1)[0]
        ax_detail.text(
            0.02, 0.055,
            f"Unresolved itineraries remain null, never zero. Most frequent segment reason:\n"
            f"{top_reason.replace('_', ' ')} ({top_count:,} segments)",
            transform=ax_detail.transAxes, ha="left", va="bottom", fontsize=7.5, color=PALETTE["muted"],
        )

    add_method_note(
        fig,
        "Iteration 49 of the documented run3→run6 checkpoint-recovery sensitivity; experienced PT legs require vehicle, line, route, boarding and alighting references. "
        "Fares use locked exact-key MTR, LRT, GMB, Ferry and franchised-bus catalogues with SHA-256 verification and no distance, reverse, full-fare or zero fallback.\n"
        "Amounts are adult-reference/base Octopus rules. Passenger concessions and transfer discounts are not modelled; therefore totals are model-rule HKD, not observed individual payments.",
        y=0.012,
    )
    png, pdf = save_figure(fig, args.output_dir, "figure_8_pt_fare_network_central", dpi=260)
    plt.close(fig)

    quoted_source = quoted.loc[quoted["trip_id"].isin(set(itineraries["trip_id"]))].copy()
    quoted_source.to_parquet(derived, index=False)
    provenance = {
        "schema_version": "progress_report_pt_fare_network_figure_v1",
        "run_identity": "candidate5b_signal_pttime1_formal50_run3_to_resume40_run6",
        "iteration": 49,
        "source_area": {
            "label": "Central-Admiralty",
            "crs": "EPSG:32650",
            "x": ORIGIN_X,
            "y": ORIGIN_Y,
            "radius_m": ORIGIN_RADIUS_M,
        },
        "experienced_pt_leg_count_all_hong_kong": int(len(legs)),
        "source_area_itinerary_count": int(len(itineraries)),
        "source_area_complete_fare_itinerary_count": int(len(resolved)),
        "source_area_complete_fare_rate": float(len(resolved) / len(itineraries)),
        "mapped_destination_count": int(len(mapped)),
        "representative_trip_ids": examples,
        "strict_fare_source_sha256": EXPECTED_SHA256,
        "limitations": [
            "adult_reference_or_base_Octopus_fares",
            "passenger_concessions_not_modelled",
            "transfer_discounts_not_modelled",
            "unresolved_fares_remain_null_and_are_excluded_from_complete_fare_aggregation",
            "checkpoint_recovery_sensitivity_not_single_process_production_run",
        ],
        "derived_quoted_leg_data": str(derived),
        "outputs": [str(png), str(pdf)],
    }
    metadata_path = args.output_dir / "figure_8_pt_fare_network_central_provenance.json"
    metadata_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
