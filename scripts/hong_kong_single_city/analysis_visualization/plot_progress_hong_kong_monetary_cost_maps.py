#!/usr/bin/env python3
"""Plot iteration-49 Hong Kong monetary costs from executed, priced trips.

The script reconstructs the exact runtime PT and private-car rule semantics and
the locked distance-only Taxi fare schedule. Unresolved PT segments or parking
quotes are never converted to zero. Fixed private-car ownership is outside the
trip-level accounting boundary.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import shlex
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from progress_report_figure_style import (
    MODE_COLORS,
    PALETTE,
    add_method_note,
    apply_progress_report_style,
    clean_map_axis,
    save_figure,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "runs/hongkong/outputs/progress_report_figures_20260824"
SOURCE = OUTPUT_DIR / "source_data"
IT49 = SOURCE / "run6_it49"
INPUTS = SOURCE / "run6_inputs"
CANONICAL_ROOT = Path(r"F:\Matsim\matsim-example-project")
GRID = (
    CANONICAL_ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/"
    "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.geojson"
)
TAXI_RULES = (
    CANONICAL_ROOT
    / "data/taxi/hongkong/processed/taxi_fare_model_v1/taxi_fare_rules.csv"
)
REMOTE_EVENTS = (
    "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260820_"
    "candidate5b_signal_pttime1_formal50_resume40_run6/output/ITERS/it.49/"
    "49.events.xml.zst"
)
EXPECTED_CAR = {
    "energy_hkd": 946112.686233778,
    "toll_hkd": 247781.0,
    "parking_hkd": 980271.0,
    "toll_entries": 9960,
    "parking_events": 16133,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--source-dir", type=Path, default=SOURCE)
    parser.add_argument("--ssh-host", default="by@100.103.8.34")
    return parser.parse_args()


def seconds(value: pd.Series) -> pd.Series:
    parts = value.str.split(":", expand=True).astype(float)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def strip_numeric(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def transit_route_modes(path: Path) -> dict[tuple[str, str], str]:
    modes: dict[tuple[str, str], str] = {}
    current_line = ""
    with gzip.open(path, "rb") as handle:
        for event, element in ET.iterparse(handle, events=("start", "end")):
            name = tag(element)
            if event == "start" and name == "transitLine":
                current_line = element.attrib["id"]
            elif event == "end" and name == "transitRoute":
                mode = next(
                    (child.text or "" for child in element if tag(child) == "transportMode"),
                    "",
                ).strip()
                modes[(current_line, element.attrib["id"])] = mode
                element.clear()
            elif event == "end" and name == "transitLine":
                current_line = ""
                element.clear()
    return modes


def station_crosswalk(path: Path, official: str, matrix_flag: str) -> dict[str, str]:
    frame = pd.read_csv(path)
    frame = frame[
        frame["mapping_status"].eq("exact") & frame[matrix_flag].astype(bool)
    ]
    result: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        value = strip_numeric(getattr(row, official))
        for facility in json.loads(row.schedule_facility_ids_json):
            result[facility] = value
    return result


def direct_crosswalk(path: Path) -> dict[str, str]:
    frame = pd.read_csv(path)
    frame = frame[frame["mapping_status"].eq("exact")]
    return {
        str(row.matsim_stop_facility_id): strip_numeric(row.official_stop_id)
        for row in frame.itertuples(index=False)
        if pd.notna(row.official_stop_id)
    }


def pt_fares(legs: pd.DataFrame, trips: pd.DataFrame, fare_root: Path, schedule: Path) -> pd.DataFrame:
    route_modes = transit_route_modes(schedule)
    pt = legs.loc[legs["mode"].eq("pt")].copy()
    pt["actual_mode"] = [
        route_modes.get((str(line), str(route)), "")
        for line, route in zip(pt["transit_line"], pt["transit_route"])
    ]
    pt["cost_hkd"] = np.nan
    pt["resolved"] = False

    layers = {
        "train": (
            station_crosswalk(
                fare_root / "mtr_station_od_v1/mtr_station_crosswalk.csv",
                "station_id",
                "in_domestic_fare_matrix",
            ),
            pd.read_parquet(
                fare_root / "mtr_station_od_v1/mtr_station_od_fare_rules.parquet"
            ).query("fare_network_scope == 'domestic_mtr_station_od'"),
            "boarding_station_id",
            "alighting_station_id",
            "adult_octopus_fare_hkd",
            False,
        ),
        "light_rail": (
            station_crosswalk(
                fare_root / "light_rail_station_od_v1/light_rail_stop_crosswalk.csv",
                "stop_id",
                "in_fare_matrix",
            ),
            pd.read_parquet(
                fare_root
                / "light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet"
            ).query("fare_network_scope == 'light_rail_station_od'"),
            "boarding_stop_id",
            "alighting_stop_id",
            "adult_octopus_fare_hkd",
            False,
        ),
        "gmb": (
            direct_crosswalk(fare_root / "gmb_fare_v1/gmb_stop_crosswalk.csv"),
            pd.read_parquet(fare_root / "gmb_fare_v1/gmb_fare_rules.parquet"),
            "boarding_stop_id",
            "alighting_stop_id",
            "published_fare_hkd",
            True,
        ),
        "ferry": (
            direct_crosswalk(fare_root / "ferry_fare_v1/ferry_stop_crosswalk.csv"),
            pd.read_parquet(fare_root / "ferry_fare_v1/ferry_fare_rules.parquet"),
            "boarding_stop_id",
            "alighting_stop_id",
            "published_fare_hkd",
            True,
        ),
        "bus": (
            direct_crosswalk(
                fare_root / "bus_scope_direction_audit_v1/bus_stop_crosswalk.csv"
            ),
            pd.read_parquet(fare_root / "bus_fare_v1/bus_fare_rules.parquet"),
            "boarding_stop_id",
            "alighting_stop_id",
            "published_fare_hkd",
            True,
        ),
    }
    for actual_mode, (crosswalk, rules, bcol, acol, ccol, route_keyed) in layers.items():
        index = pt.index[pt["actual_mode"].eq(actual_mode)]
        if not len(index):
            continue
        sub = pt.loc[index, ["transit_line", "transit_route", "access_stop_id", "egress_stop_id"]].copy()
        sub["boarding"] = sub["access_stop_id"].map(crosswalk)
        sub["alighting"] = sub["egress_stop_id"].map(crosswalk)
        available = rules[rules[ccol].notna() & rules["record_status"].eq("available")].copy()
        available["boarding"] = available[bcol].map(strip_numeric)
        available["alighting"] = available[acol].map(strip_numeric)
        if route_keyed:
            keycols = ["matsim_line_id", "matsim_route_id", "boarding", "alighting"]
            available = available.drop_duplicates(keycols).set_index(keycols)[ccol]
            keys = pd.MultiIndex.from_arrays(
                [sub["transit_line"], sub["transit_route"], sub["boarding"], sub["alighting"]]
            )
        else:
            keycols = ["boarding", "alighting"]
            available = available.drop_duplicates(keycols).set_index(keycols)[ccol]
            keys = pd.MultiIndex.from_arrays([sub["boarding"], sub["alighting"]])
        values = available.reindex(keys).to_numpy(dtype=float)
        pt.loc[index, "cost_hkd"] = values
        pt.loc[index, "resolved"] = np.isfinite(values)

    grouped = pt.groupby(["person", "trip_id"], as_index=False).agg(
        segment_count=("mode", "size"),
        resolved_segments=("resolved", "sum"),
        cost_hkd=("cost_hkd", "sum"),
        segment_modes=("actual_mode", lambda x: "+".join(x)),
    )
    grouped["fully_resolved"] = grouped["resolved_segments"].eq(grouped["segment_count"])
    origins = trips.loc[trips["main_mode"].eq("pt"), [
        "person", "trip_id", "start_x", "start_y"
    ]]
    grouped = origins.merge(grouped, on=["person", "trip_id"], how="left", validate="one_to_one")
    grouped["mode"] = "pt"
    return grouped


def taxi_fares(legs: pd.DataFrame, trips: pd.DataFrame, rules_path: Path) -> pd.DataFrame:
    taxi = legs.loc[legs["mode"].eq("taxi"), [
        "person", "trip_id", "distance", "vehicle_id"
    ]].copy()
    taxi["taxi_type"] = np.select(
        [
            taxi["vehicle_id"].str.startswith("hk_taxi_urban_"),
            taxi["vehicle_id"].str.startswith("hk_taxi_nt_"),
            taxi["vehicle_id"].str.startswith("hk_taxi_lantau_"),
        ],
        ["urban_taxi", "new_territories_taxi", "lantau_taxi"],
        default="",
    )
    rules = pd.read_csv(rules_path).set_index("taxi_type")
    taxi["cost_hkd"] = np.nan
    for taxi_type, rule in rules.iterrows():
        mask = taxi["taxi_type"].eq(taxi_type)
        distance = taxi.loc[mask, "distance"].astype(float)
        first = np.ceil(
            np.maximum(
                np.minimum(distance, rule.first_tier_end_distance_m)
                - rule.flagfall_distance_m,
                0,
            )
            / rule.first_tier_increment_distance_m
        )
        second = np.ceil(
            np.maximum(distance - rule.first_tier_end_distance_m, 0)
            / rule.second_tier_increment_distance_m
        )
        taxi.loc[mask, "cost_hkd"] = (
            rule.flagfall_hkd
            + first * rule.first_tier_increment_hkd
            + second * rule.second_tier_increment_hkd
        )
    origins = trips.loc[trips["main_mode"].eq("taxi"), [
        "person", "trip_id", "start_x", "start_y"
    ]]
    taxi = origins.merge(taxi, on=["person", "trip_id"], how="left", validate="one_to_one")
    taxi["fully_resolved"] = taxi["cost_hkd"].notna()
    taxi["mode"] = "taxi"
    return taxi


def extract_toll_events(host: str, output: Path, mapping: pd.DataFrame) -> None:
    links = sorted(mapping.loc[mapping["mapping_status"].eq("mapped"), "matsim_link_id"].unique())
    pattern = "|".join(re.escape(link) for link in links)
    expression = f'type="entered link" link="({pattern})" vehicle="hk_vehicle_'
    remote_command = f"zstdgrep -E {shlex.quote(expression)} {shlex.quote(REMOTE_EVENTS)}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        completed = subprocess.run(
            ["ssh", "-T", host, remote_command],
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr)


EVENT_RE = re.compile(
    r'time="(?P<time>[0-9.]+)" type="entered link" '
    r'link="(?P<link>[^"]+)" vehicle="(?P<vehicle>[^"]+)"'
)


def toll_rate(rules: pd.DataFrame, facility: str, time_s: float) -> float:
    selected = rules[(rules["toll_facility_id"].eq(facility)) & rules["vehicle_class"].eq("private_car")]
    all_day = selected[selected["day_of_week_code"].eq("ALL")]
    selected = all_day if len(all_day) else selected[selected["day_of_week_code"].eq("A")]
    clock = time_s % 86400
    row = selected[(selected["start_time_s"] <= clock) & (clock < selected["end_time_s"] + 1)]
    if len(row) != 1:
        raise ValueError(f"No unique toll quote for {facility} at {time_s}")
    return float(row.iloc[0]["toll_hkd"])


def activity_group(value: str) -> str:
    if value == "home": return "home"
    if value in {"work", "work_mobile", "business"}: return "work"
    if value.startswith("school") or value.startswith("education"): return "education"
    if value == "shopping": return "shopping"
    if value in {"dining", "leisure", "social", "vfr", "primary_activity", "secondary_activity"}: return "leisure"
    if value in {"medical", "personal_business"}: return "medical_personal_business"
    if value == "accommodation": return "visitor_accommodation"
    if value in {"border", "external_activity"}: return "border"
    return "other"


def zone_group(zone: int) -> str:
    if 1 <= zone <= 4: return "hong_kong_island"
    if 5 <= zone <= 13: return "kowloon_urban"
    if 14 <= zone <= 26: return "new_territories_lantau"
    raise ValueError(zone)


def parking_quote(rule: pd.Series, arrival: float, departure: float) -> float:
    method = rule.pricing_method
    if method == "home_temporary_cost_zero_fixed_parking_separate": return 0.0
    if method in {"representative_day_pass", "representative_night_pass"}:
        return float(rule.daily_cap_hkd)
    if method not in {"hourly_or_part_by_arrival_clock", "hourly_or_part_capped_at_ten_hours"}:
        raise ValueError(method)
    increment = float(rule.billing_increment_s)
    units = int(math.ceil(max(departure - arrival, 0) / increment))
    amount = 0.0
    for unit in range(units):
        clock = (arrival + unit * increment) % 86400
        amount += (
            float(rule.hourly_day_hkd)
            if rule.day_period_start_s <= clock < rule.day_period_end_s
            else float(rule.hourly_night_hkd)
        )
    return max(float(rule.minimum_charge_hkd), min(amount, float(rule.daily_cap_hkd)))


def car_costs(
    legs: pd.DataFrame,
    trips: pd.DataFrame,
    car_root: Path,
    toll_events_path: Path,
    host: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    feasibility = pd.read_parquet(
        car_root / "car_leg_input_feasibility.parquet",
        columns=["vehicle_ref_id", "vehicle_class", "destination_facility_id", "destination_tcs_zone"],
    )
    vehicle_class = feasibility[["vehicle_ref_id", "vehicle_class"]].drop_duplicates()
    car = legs.loc[legs["mode"].eq("car"), [
        "person", "trip_id", "dep_time", "trav_time", "distance", "vehicle_id"
    ]].copy()
    car["departure_s"] = seconds(car["dep_time"])
    car["arrival_s"] = car["departure_s"] + seconds(car["trav_time"])
    car = car.merge(vehicle_class, left_on="vehicle_id", right_on="vehicle_ref_id", how="left", validate="many_to_one")
    car = car.loc[car["vehicle_class"].eq("private_car")].copy()
    energy_rate = float(
        pd.read_csv(car_root / "car_energy_cost_parameters.csv")
        .query("scenario == 'base'")["energy_cost_hkd_per_km"].iloc[0]
    )
    car["energy_hkd"] = car["distance"].astype(float) / 1000 * energy_rate
    car["toll_hkd"] = 0.0

    mapping = pd.read_csv(car_root / "toll_facility_network_mapping.csv")
    if not toll_events_path.exists():
        extract_toll_events(host, toll_events_path, mapping)
    facility_by_link = dict(zip(mapping["matsim_link_id"], mapping["canonical_facility_id"]))
    toll_rules = pd.read_csv(car_root / "car_toll_rules.csv")
    events = []
    for line in toll_events_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(line)
        if match:
            events.append(match.groupdict())
    events = pd.DataFrame(events)
    events["time_s"] = events["time"].astype(float)
    events["toll_hkd"] = [
        toll_rate(toll_rules, facility_by_link[link], time_s)
        for link, time_s in zip(events["link"], events["time_s"])
    ]
    assigned_toll_entries = 0
    for vehicle, event_group in events.groupby("vehicle"):
        candidates = car.index[car["vehicle_id"].eq(vehicle)]
        if not len(candidates):
            continue
        ordered = car.loc[candidates].sort_values("departure_s")
        dep = ordered["departure_s"].to_numpy()
        arr = ordered["arrival_s"].to_numpy()
        for event in event_group.itertuples(index=False):
            position = int(np.searchsorted(dep, event.time_s, side="right") - 1)
            if position < 0 or event.time_s > arr[position] + 1:
                raise ValueError(f"Toll event outside private-car leg: {event}")
            car.loc[ordered.index[position], "toll_hkd"] += event.toll_hkd
            assigned_toll_entries += 1

    car = car.merge(
        trips[["person", "trip_id", "start_x", "start_y", "end_facility_id", "end_activity_type"]],
        on=["person", "trip_id"], how="left", validate="one_to_one",
    )
    car = car.sort_values(["vehicle_id", "departure_s"])
    car["next_departure_s"] = car.groupby("vehicle_id")["departure_s"].shift(-1)
    car["parking_hkd"] = np.nan
    zone_lookup = (
        feasibility.dropna(subset=["destination_tcs_zone"])
        .assign(destination_tcs_zone=lambda x: x["destination_tcs_zone"].astype(int))
        .drop_duplicates(["destination_facility_id"])
        .set_index("destination_facility_id")["destination_tcs_zone"].to_dict()
    )
    repairs = pd.read_csv(car_root / "facility_tcs_zone_repairs.csv")
    zone_lookup.update(dict(zip(repairs["destination_facility_id"], repairs["tcs_zone"].astype(int))))
    parking_rules = pd.read_csv(car_root / "parking_cost_rules_repository_relative.csv")
    parking_rules = parking_rules[
        parking_rules["scenario"].eq("base") & parking_rules["marginal_leg_cost_resolved"].astype(bool)
    ].set_index(["zone_group", "activity_group"])
    for index, row in car[car["next_departure_s"].notna()].iterrows():
        facility = str(row.end_facility_id).split("__hk_car_anchor__", 1)[0]
        zone = zone_lookup.get(facility)
        group = activity_group(str(row.end_activity_type))
        if zone is None or (zone_group(zone), group) not in parking_rules.index:
            continue
        rule = parking_rules.loc[(zone_group(zone), group)]
        car.loc[index, "parking_hkd"] = parking_quote(rule, row.arrival_s, row.next_departure_s)
    car["fully_resolved"] = car["parking_hkd"].notna() | car["next_departure_s"].isna()
    # The runtime deliberately creates no terminal parking event in this run.
    car.loc[car["next_departure_s"].isna(), "fully_resolved"] = False
    car["cost_hkd"] = car[["energy_hkd", "toll_hkd", "parking_hkd"]].sum(axis=1, min_count=3)
    car["mode"] = "car"
    qa = {
        "energy_hkd_reconstructed_from_rounded_leg_distance": float(car["energy_hkd"].sum()),
        "energy_hkd_runtime": EXPECTED_CAR["energy_hkd"],
        "toll_hkd": float(car["toll_hkd"].sum()),
        "toll_entries": int(assigned_toll_entries),
        "parking_hkd": float(car["parking_hkd"].sum()),
        "parking_events": int(car["parking_hkd"].notna().sum()),
    }
    if qa["toll_hkd"] != EXPECTED_CAR["toll_hkd"] or qa["toll_entries"] != EXPECTED_CAR["toll_entries"]:
        raise AssertionError(qa)
    # Public leg exports serialize whole seconds; one boundary-sensitive hourly
    # parking increment differs by HK$14 (0.0014%) from the event-native scorer.
    if abs(qa["parking_hkd"] - EXPECTED_CAR["parking_hkd"]) > 14.01 or qa["parking_events"] != EXPECTED_CAR["parking_events"]:
        raise AssertionError(qa)
    return car, qa


def cmap(color: str) -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("progress", ["#F7F8F7", "#D8E0DE", color])


def plot_panel(ax, grid: gpd.GeoDataFrame, data: pd.DataFrame, title: str, color: str, show_bubbles: bool = False):
    joined = gpd.GeoDataFrame(
        data,
        geometry=gpd.points_from_xy(data["start_x"], data["start_y"]),
        crs="EPSG:32650",
    )
    assigned = gpd.sjoin(joined, grid[["grid_id", "geometry"]], predicate="within", how="left")
    stats = assigned.dropna(subset=["grid_id"]).groupby("grid_id").agg(
        mean_hkd=("cost_hkd", "mean"), total_hkd=("cost_hkd", "sum"), trips=("cost_hkd", "size")
    )
    mapped = grid.join(stats, on="grid_id")
    positive = mapped["mean_hkd"].dropna()
    vmax = float(positive.quantile(0.95)) if len(positive) else 1.0
    mapped.plot(ax=ax, color=PALETTE["land"], edgecolor="#C8CDCB", linewidth=0.18)
    mapped.dropna(subset=["mean_hkd"]).plot(
        ax=ax, column="mean_hkd", cmap=cmap(color), norm=Normalize(0, vmax),
        edgecolor="#BBC1BF", linewidth=0.16,
    )
    grid.dissolve().boundary.plot(ax=ax, color=PALETTE["boundary"], linewidth=0.65)
    if show_bubbles and mapped["total_hkd"].notna().any():
        top = mapped.nlargest(18, "total_hkd").copy()
        centers = top.geometry.centroid
        max_total = top["total_hkd"].max()
        ax.scatter(centers.x, centers.y, s=9 + 95 * np.sqrt(top["total_hkd"] / max_total),
                   facecolors="none", edgecolors=PALETTE["brick"], linewidths=0.8, alpha=0.75)
    clean_map_axis(ax)
    ax.set_title(title, loc="left", fontsize=12.2, pad=4)
    ax.text(0.015, 0.02,
            f"{len(data):,} priced trips  |  mean HK${data.cost_hkd.mean():.1f}\n"
            f"p50 HK${data.cost_hkd.median():.1f}  |  p90 HK${data.cost_hkd.quantile(.9):.1f}",
            transform=ax.transAxes, fontsize=7.8, color=PALETTE["text"],
            bbox=dict(facecolor="white", edgecolor="#D1D5D3", alpha=.92, boxstyle="round,pad=.3"))
    scalar = mpl.cm.ScalarMappable(norm=Normalize(0, vmax), cmap=cmap(color))
    bar = ax.figure.colorbar(scalar, ax=ax, orientation="horizontal", fraction=.035, pad=.015, shrink=.53)
    bar.set_label("Mean modeled monetary cost (HKD / priced trip); color clipped at p95", fontsize=7.3)
    bar.ax.tick_params(labelsize=7)
    return stats


def main() -> None:
    args = parse_args()
    source = args.source_dir
    it49 = source / "run6_it49"
    inputs = source / "run6_inputs"
    trips = pd.read_csv(it49 / "49.trips.csv.zst", sep=";", compression="zstd")
    legs = pd.read_csv(it49 / "49.legs.csv.zst", sep=";", compression="zstd")
    pt = pt_fares(legs, trips, inputs / "pt_fare", inputs / "transitSchedule.xml.gz")
    taxi = taxi_fares(legs, trips, TAXI_RULES)
    car, car_qa = car_costs(
        legs, trips, inputs / "car_cost", source / "run6_it49/toll_link_enter_events.xmlfrag",
        args.ssh_host,
    )
    resolved_pt = pt[pt["fully_resolved"] & pt["cost_hkd"].notna()].copy()
    resolved_taxi = taxi[taxi["fully_resolved"]].copy()
    resolved_car = car[car["fully_resolved"] & car["cost_hkd"].notna()].copy()
    overall = pd.concat(
        [resolved_pt[["start_x", "start_y", "cost_hkd", "mode"]],
         resolved_car[["start_x", "start_y", "cost_hkd", "mode"]],
         resolved_taxi[["start_x", "start_y", "cost_hkd", "mode"]]],
        ignore_index=True,
    )
    grid = gpd.read_file(GRID).to_crs("EPSG:32650")
    apply_progress_report_style()
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 9.35))
    fig.suptitle("Hong Kong modeled monetary costs — iteration 49", fontsize=18.5, y=.993)
    fig.text(.5, .958,
             "Completed and fully resolved PT, private-car and Taxi trips; amounts in HKD, not utility scores",
             ha="center", color=PALETTE["muted"], fontsize=10.5)
    plot_panel(axes[0, 0], grid, overall, "A  All priced modes", PALETTE["brick"], True)
    plot_panel(axes[0, 1], grid, resolved_pt, "B  Public transport fare", MODE_COLORS["pt"])
    plot_panel(axes[1, 0], grid, resolved_car, "C  Private car: energy + toll + parking", MODE_COLORS["car"])
    plot_panel(axes[1, 1], grid, resolved_taxi, "D  Taxi meter fare (distance-only model)", MODE_COLORS["taxi"])
    fig.legend(
        handles=[Line2D([0], [0], marker="o", linestyle="none", markerfacecolor="none",
                        markeredgecolor=PALETTE["brick"], label="Top origin grids by model-day priced spend")],
        loc="upper left", bbox_to_anchor=(.075, .902), fontsize=7.7,
    )
    fig.subplots_adjust(left=.025, right=.985, top=.890, bottom=.055, wspace=.02, hspace=.10)
    add_method_note(
        fig,
        "Run3 checkpoint (iterations 0–40) + immutable run6 recovery (41–49), final executed iteration 49. "
        "PT requires every actual segment to resolve under the strict five-layer catalog; unresolved is never zero. "
        "Car excludes motorcycles and fixed ownership; terminal or unresolved parking is excluded. Taxi excludes wait, booking, baggage and tunnel surcharges.",
        y=.006,
    )
    save_figure(fig, args.output_dir, "figure_b_hong_kong_monetary_cost_maps")
    plt.close(fig)

    summary = {
        "run_identity": "run3 it.0-40 checkpoint + resume40 run6 it.41-49",
        "iteration": 49,
        "statistics": {
            "pt_selected": int(len(pt)), "pt_fully_resolved": int(len(resolved_pt)),
            "car_selected_private": int(len(car)), "car_fully_resolved": int(len(resolved_car)),
            "taxi_completed": int(len(taxi)), "taxi_priced": int(len(resolved_taxi)),
            "overall_priced_trips": int(len(overall)),
        },
        "car_runtime_reconciliation": car_qa,
        "exclusions": [
            "walk", "car_passenger passenger-side cost allocation", "school_bus",
            "unresolved PT fare chains", "unresolved or terminal private-car parking",
            "private-car fixed ownership", "Taxi waiting/booking/baggage/tunnel surcharges",
        ],
    }
    (args.output_dir / "figure_b_hong_kong_monetary_cost_maps_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
