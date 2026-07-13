"""Analyze actual bus/metro composition inside generic MATSim PT trips."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = (
    ROOT
    / "output-fuzhou-transit-mode-choice-2pct-busprio-carcap5-floor-snapspread-choicefix-realpt-reroute-10"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE)
    return parser.parse_args()


def duration_seconds(series: pd.Series) -> pd.Series:
    return pd.to_timedelta(series.fillna("00:00:00")).dt.total_seconds()


def analyze(output_dir: Path) -> dict[str, Any]:
    legs_path = output_dir / "output_legs.csv.zst"
    trips_path = output_dir / "output_trips.csv.zst"
    if not legs_path.exists() or not trips_path.exists():
        raise FileNotFoundError(f"missing output_legs/output_trips in {output_dir}")
    legs = pd.read_csv(legs_path, sep=";")
    trips = pd.read_csv(trips_path, sep=";")
    trips["travel_s"] = duration_seconds(trips["trav_time"])
    trips["wait_s"] = duration_seconds(trips["wait_time"])

    mode_rows: list[dict[str, Any]] = []
    for mode, group in trips.groupby("main_mode", dropna=False):
        mode_rows.append(
            {
                "main_mode": str(mode),
                "trips": int(len(group)),
                "share_pct": round(len(group) / len(trips) * 100, 4),
                "avg_travel_min": round(group["travel_s"].mean() / 60, 3),
                "avg_wait_min": round(group["wait_s"].mean() / 60, 3),
                "avg_distance_km": round(group["traveled_distance"].mean() / 1000, 3),
                "aggregate_speed_kmh": round(
                    group["traveled_distance"].sum() / max(group["travel_s"].sum(), 1e-9) * 3.6, 3
                ),
            }
        )

    pt_legs = legs[legs["mode"].eq("pt")].copy()
    pt_legs["route_mode"] = np.select(
        [
            pt_legs["transit_line"].astype(str).str.startswith("metro_"),
            pt_legs["transit_line"].astype(str).str.startswith("bus_"),
        ],
        ["metro", "bus"],
        default="unknown",
    )
    pt_legs["travel_s"] = duration_seconds(pt_legs["trav_time"])
    pt_legs["wait_s"] = duration_seconds(pt_legs["wait_time"])
    flags = pt_legs.assign(
        has_bus=pt_legs["route_mode"].eq("bus"),
        has_metro=pt_legs["route_mode"].eq("metro"),
        has_unknown=pt_legs["route_mode"].eq("unknown"),
    ).groupby("trip_id").agg(
        has_bus=("has_bus", "max"),
        has_metro=("has_metro", "max"),
        has_unknown=("has_unknown", "max"),
        pt_boardings=("mode", "size"),
    )
    flags["pt_submode"] = np.select(
        [
            flags["has_bus"] & flags["has_metro"],
            flags["has_metro"] & ~flags["has_bus"],
            flags["has_bus"] & ~flags["has_metro"],
        ],
        ["bus+metro", "metro_only", "bus_only"],
        default="unknown",
    )
    pt_trips = trips.merge(flags, left_on="trip_id", right_index=True, how="inner")

    submode_rows: list[dict[str, Any]] = []
    for submode, group in pt_trips.groupby("pt_submode"):
        submode_rows.append(
            {
                "pt_submode": submode,
                "trips": int(len(group)),
                "share_of_pt_pct": round(len(group) / max(len(pt_trips), 1) * 100, 4),
                "share_of_all_trips_pct": round(len(group) / max(len(trips), 1) * 100, 4),
                "persons": int(group["person"].nunique()),
                "avg_trip_min": round(group["travel_s"].mean() / 60, 3),
                "median_trip_min": round(group["travel_s"].median() / 60, 3),
                "avg_wait_min": round(group["wait_s"].mean() / 60, 3),
                "avg_distance_km": round(group["traveled_distance"].mean() / 1000, 3),
                "avg_pt_boardings": round(group["pt_boardings"].mean(), 3),
            }
        )

    leg_mode_rows: list[dict[str, Any]] = []
    for route_mode, group in pt_legs.groupby("route_mode"):
        leg_mode_rows.append(
            {
                "route_mode": route_mode,
                "boardings": int(len(group)),
                "persons": int(group["person"].nunique()),
                "avg_leg_min": round(group["travel_s"].mean() / 60, 3),
                "avg_wait_min": round(group["wait_s"].mean() / 60, 3),
                "avg_leg_distance_km": round(group["distance"].mean() / 1000, 3),
                "aggregate_in_vehicle_speed_kmh": round(
                    group["distance"].sum() / max(group["travel_s"].sum(), 1e-9) * 3.6, 3
                ),
            }
        )

    metro_trip_mask = flags["has_metro"]
    metro_trip_ids = set(flags.index[metro_trip_mask])
    metro_persons = set(pt_legs.loc[pt_legs["trip_id"].isin(metro_trip_ids), "person"].astype(str))
    stuck_path = output_dir / "analysis" / "population" / "stuck_agents.csv"
    stuck_text = stuck_path.read_text(encoding="utf-8-sig") if stuck_path.exists() else ""
    return {
        "output_dir": str(output_dir),
        "all_trips": int(len(trips)),
        "pt_trips": int(len(pt_trips)),
        "metro_involved_trips": int(metro_trip_mask.sum()),
        "metro_involved_share_of_all_pct": round(metro_trip_mask.sum() / max(len(trips), 1) * 100, 4),
        "metro_involved_share_of_pt_pct": round(metro_trip_mask.sum() / max(len(pt_trips), 1) * 100, 4),
        "metro_users": len(metro_persons),
        "mode_summary": mode_rows,
        "pt_submode_summary": submode_rows,
        "pt_leg_route_mode_summary": leg_mode_rows,
        "stuck_agents_csv": stuck_text,
    }


def metric_lookup(metrics: dict[str, Any], section: str, key: str, value: str) -> dict[str, Any]:
    return next((row for row in metrics.get(section, []) if str(row.get(key)) == value), {})


def main() -> None:
    args = parse_args()
    metrics = analyze(args.output_dir)
    baseline = analyze(args.baseline_dir) if args.baseline_dir.exists() else None
    comparison: dict[str, Any] = {}
    if baseline is not None:
        new_bus = metric_lookup(metrics, "pt_leg_route_mode_summary", "route_mode", "bus")
        old_bus = metric_lookup(baseline, "pt_leg_route_mode_summary", "route_mode", "bus")
        comparison = {
            "baseline_dir": str(args.baseline_dir),
            "metro_involved_trips_before": baseline["metro_involved_trips"],
            "metro_involved_trips_after": metrics["metro_involved_trips"],
            "metro_share_all_pct_before": baseline["metro_involved_share_of_all_pct"],
            "metro_share_all_pct_after": metrics["metro_involved_share_of_all_pct"],
            "bus_in_vehicle_speed_kmh_before": old_bus.get("aggregate_in_vehicle_speed_kmh"),
            "bus_in_vehicle_speed_kmh_after": new_bus.get("aggregate_in_vehicle_speed_kmh"),
        }

    analysis_dir = args.output_dir / "analysis" / "population"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(metrics["mode_summary"]).to_csv(
        analysis_dir / "main_mode_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(metrics["pt_submode_summary"]).to_csv(
        analysis_dir / "pt_submode_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(metrics["pt_leg_route_mode_summary"]).to_csv(
        analysis_dir / "pt_leg_route_mode_summary.csv", index=False, encoding="utf-8-sig"
    )
    (analysis_dir / "pt_submode_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (analysis_dir / "pt_submode_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"metrics": metrics, "comparison": comparison}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
