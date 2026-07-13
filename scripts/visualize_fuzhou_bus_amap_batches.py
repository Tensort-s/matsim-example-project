#!/usr/bin/env python
"""Merge and visualize batched AMap Fuzhou bus extraction outputs.

The AMap coordinates are GCJ-02 lon/lat. The figures are for data inspection,
not yet for MATSim network coordinates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def read_geojson(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("features", [])


def write_geojson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dedupe_features(features: list[dict], key: str) -> list[dict]:
    seen = set()
    out = []
    for feat in features:
        props = feat.get("properties") or {}
        value = props.get(key)
        if not value:
            value = json.dumps(feat.get("geometry"), ensure_ascii=False)
        if value in seen:
            continue
        seen.add(value)
        out.append(feat)
    return out


def plot_trajectories_and_stops(line_features: list[dict], stop_df: pd.DataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 12))
    for feat in line_features:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        ax.plot(xs, ys, linewidth=0.45, alpha=0.22, color="#1f77b4")
    if not stop_df.empty:
        ax.scatter(stop_df["lon"], stop_df["lat"], s=3, alpha=0.45, color="#111111", linewidths=0)
    ax.set_title(f"Fuzhou bus network from AMap batches 1-90\n{len(line_features)} line trajectories, {len(stop_df)} unique stops (GCJ-02)")
    ax.set_xlabel("Longitude (GCJ-02)")
    ax.set_ylabel("Latitude (GCJ-02)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.18)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_station_density(stop_df: pd.DataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 10))
    hb = ax.hexbin(stop_df["lon"], stop_df["lat"], gridsize=70, mincnt=1, cmap="magma")
    cb = fig.colorbar(hb, ax=ax)
    cb.set_label("Stop count")
    ax.set_title(f"Fuzhou bus stop density from AMap batches 1-90\n{len(stop_df)} unique stops (GCJ-02)")
    ax.set_xlabel("Longitude (GCJ-02)")
    ax.set_ylabel("Latitude (GCJ-02)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_adjacent_edges(edge_df: pd.DataFrame, stop_df: pd.DataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 12))
    for _, row in edge_df.iterrows():
        vals = [row.get("from_lon"), row.get("from_lat"), row.get("to_lon"), row.get("to_lat")]
        if pd.isna(vals).any():
            continue
        ax.plot([vals[0], vals[2]], [vals[1], vals[3]], linewidth=0.25, alpha=0.08, color="#2ca02c")
    if not stop_df.empty:
        ax.scatter(stop_df["lon"], stop_df["lat"], s=2, alpha=0.35, color="#000000", linewidths=0)
    ax.set_title(f"Fuzhou bus adjacent-stop edges from AMap batches 1-90\n{len(edge_df)} directed adjacent-stop records")
    ax.set_xlabel("Longitude (GCJ-02)")
    ax.set_ylabel("Latitude (GCJ-02)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_data_coverage(line_df: pd.DataFrame, svc_df: pd.DataFrame, out_png: Path) -> None:
    line_df = line_df.copy()
    svc_df = svc_df.copy()
    if not svc_df.empty and "headway_minutes" in svc_df.columns:
        nonempty = svc_df[svc_df["headway_minutes"].notna() & (svc_df["headway_minutes"].astype(str) != "")]
        lines_with_headway = set(nonempty["line_id"].astype(str))
    else:
        nonempty = pd.DataFrame()
        lines_with_headway = set()
    line_df["has_headway"] = line_df["line_id"].astype(str).isin(lines_with_headway)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))

    # Headway coverage.
    counts = line_df["has_headway"].value_counts().reindex([True, False], fill_value=0)
    axes[0].bar(["with headway", "missing"], [counts[True], counts[False]], color=["#2ca02c", "#d62728"])
    axes[0].set_title("Headway coverage")
    axes[0].set_ylabel("Line/direction records")
    for i, v in enumerate([counts[True], counts[False]]):
        axes[0].text(i, v, str(int(v)), ha="center", va="bottom")

    # Line type.
    type_label = (
        line_df["line_type"]
        .fillna("(missing)")
        .replace(
            {
                "": "(missing)",
                "普通公交": "regular bus",
                "旅游专线": "tourist line",
                "快速公交": "BRT/express bus",
                "夜班公交": "night bus",
            }
        )
    )
    type_counts = type_label.value_counts().head(8)
    axes[1].barh(type_counts.index[::-1], type_counts.values[::-1], color="#1f77b4")
    axes[1].set_title("Line types")
    axes[1].set_xlabel("Records")

    # Stop count distribution.
    axes[2].hist(line_df["stop_count"].dropna(), bins=30, color="#9467bd", alpha=0.85)
    axes[2].set_title("Stops per line/direction")
    axes[2].set_xlabel("Stop count")
    axes[2].set_ylabel("Records")

    fig.suptitle(f"AMap bus batches 1-90 data coverage: {len(line_df)} unique line/direction records")
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", action="append", required=True, help="AMap bus extraction output directory. Repeatable.")
    parser.add_argument("--output-dir", default="data/transit/fuzhou_bus_amap_wikipedia_1_90_visualization")
    args = parser.parse_args()

    batch_dirs = [Path(p) for p in args.batch_dir]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    line_dfs = []
    stop_dfs = []
    stop_by_line_dfs = []
    edge_dfs = []
    svc_dfs = []
    line_features = []
    station_features = []
    edge_features_geo = []

    for folder in batch_dirs:
        line_dfs.append(read_csv(folder / "amap_bus_lines.csv"))
        stop_dfs.append(read_csv(folder / "amap_bus_stations.csv"))
        stop_by_line_dfs.append(read_csv(folder / "amap_bus_stops_by_line.csv"))
        edge_dfs.append(read_csv(folder / "amap_bus_adjacent_stop_edges.csv"))
        svc_dfs.append(read_csv(folder / "amap_bus_service_frequency.csv"))
        line_features.extend(read_geojson(folder / "amap_bus_line_trajectories.geojson"))
        station_features.extend(read_geojson(folder / "amap_bus_stations.geojson"))
        edge_features_geo.extend(read_geojson(folder / "amap_bus_adjacent_stop_edges.geojson"))

    line_df = pd.concat([df for df in line_dfs if not df.empty], ignore_index=True).drop_duplicates("line_id")
    stop_df = pd.concat([df for df in stop_dfs if not df.empty], ignore_index=True).drop_duplicates("station_id")
    stop_by_line_df = pd.concat([df for df in stop_by_line_dfs if not df.empty], ignore_index=True).drop_duplicates("occurrence_id")
    edge_df = pd.concat([df for df in edge_dfs if not df.empty], ignore_index=True).drop_duplicates("edge_id")
    svc_df = pd.concat([df for df in svc_dfs if not df.empty], ignore_index=True).drop_duplicates()
    line_features = dedupe_features(line_features, "line_id")
    station_features = dedupe_features(station_features, "station_id")
    edge_features_geo = dedupe_features(edge_features_geo, "edge_id")

    line_df.to_csv(output_dir / "combined_amap_bus_lines.csv", index=False, encoding="utf-8-sig")
    stop_df.to_csv(output_dir / "combined_amap_bus_stations.csv", index=False, encoding="utf-8-sig")
    stop_by_line_df.to_csv(output_dir / "combined_amap_bus_stops_by_line.csv", index=False, encoding="utf-8-sig")
    edge_df.to_csv(output_dir / "combined_amap_bus_adjacent_stop_edges.csv", index=False, encoding="utf-8-sig")
    svc_df.to_csv(output_dir / "combined_amap_bus_service_frequency.csv", index=False, encoding="utf-8-sig")
    write_geojson(output_dir / "combined_amap_bus_line_trajectories.geojson", line_features)
    write_geojson(output_dir / "combined_amap_bus_stations.geojson", station_features)
    write_geojson(output_dir / "combined_amap_bus_adjacent_stop_edges.geojson", edge_features_geo)

    plot_trajectories_and_stops(line_features, stop_df, output_dir / "amap_bus_1_90_network_overview.png")
    plot_station_density(stop_df, output_dir / "amap_bus_1_90_stop_density.png")
    plot_adjacent_edges(edge_df, stop_df, output_dir / "amap_bus_1_90_adjacent_stop_edges.png")
    plot_data_coverage(line_df, svc_df, output_dir / "amap_bus_1_90_data_coverage.png")

    nonempty = svc_df[svc_df["headway_minutes"].notna() & (svc_df["headway_minutes"].astype(str) != "")] if not svc_df.empty else pd.DataFrame()
    summary = {
        "batch_dirs": [str(p) for p in batch_dirs],
        "unique_line_direction_records": int(len(line_df)),
        "unique_station_records": int(len(stop_df)),
        "stop_occurrences": int(len(stop_by_line_df)),
        "adjacent_stop_edges": int(len(edge_df)),
        "line_trajectory_features": int(len(line_features)),
        "service_frequency_rows": int(len(svc_df)),
        "nonempty_headway_rows": int(len(nonempty)),
        "line_direction_records_with_headway": int(nonempty["line_id"].astype(str).nunique()) if not nonempty.empty else 0,
        "outputs": sorted(p.name for p in output_dir.glob("*")),
    }
    (output_dir / "visualization_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
