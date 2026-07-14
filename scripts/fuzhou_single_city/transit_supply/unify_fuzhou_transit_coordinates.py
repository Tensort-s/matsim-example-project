"""Unify Fuzhou bus/metro transit coordinates for MATSim.

This script creates a new consolidated transit coordinate directory without
modifying the source final bus/metro datasets.  It preserves GCJ-02 and WGS84
coordinates where available, and adds EPSG:32650 coordinates for MATSim.

Important source-coordinate assumptions:
- Bus stop tables already contain GCJ-02, WGS84, and EPSG:32650 columns.
- Bus trajectory GeoJSON coordinates are already WGS84; do not GCJ-correct them
  again.
- Metro active CSV/GeoJSON lon/lat coordinates are AMap GCJ-02 and need
  GCJ-02 -> WGS84 -> EPSG:32650 conversion.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import shutil
from datetime import datetime
from typing import Any

import geopandas as gpd
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET_CRS = "EPSG:32650"
WGS84 = "EPSG:4326"

BUS_FINAL = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_amap_stop_line_final_20260709"
METRO_FINAL = PROJECT_ROOT / "data" / "transit" / "fuzhou_metro_final_20260709"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "transit" / "fuzhou_transit_coordinates_unified_20260709"

BUS_STOPS = BUS_FINAL / "bus_lines" / "amap_bus_stops_complete.csv"
BUS_STOPS_BY_LINE = BUS_FINAL / "bus_lines" / "amap_bus_stops_by_line_full.csv"
BUS_TRAJECTORIES = BUS_FINAL / "bus_lines" / "amap_bus_line_trajectories_full.geojson"

METRO_STATIONS = METRO_FINAL / "amap_active" / "amap_metro_stations.csv"
METRO_STOPS_BY_LINE = METRO_FINAL / "amap_active" / "amap_metro_stops_by_line.csv"
METRO_TRAJECTORIES = METRO_FINAL / "amap_active" / "amap_metro_line_trajectories.geojson"


def out_of_china(lon: float, lat: float) -> bool:
    return lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271


def transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    if out_of_china(lon, lat):
        return lon, lat
    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlng = transform_lng(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - 0.00669342162296594323 * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((6335552.717000426 * magic) / (sqrtmagic * magic) * math.pi)
    dlng = (dlng * 180.0) / (6378245.0 / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlng, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    glon, glat = wgs84_to_gcj02(lon, lat)
    return lon * 2 - glon, lat * 2 - glat


def ensure_dirs(out_dir: pathlib.Path) -> None:
    for sub in ["bus", "metro", "combined", "visualization", "metadata"]:
        (out_dir / sub).mkdir(parents=True, exist_ok=True)


def read_geojson(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_geojson(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def float_series(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def point_geojson_from_xy(df: pd.DataFrame, lon_col: str, lat_col: str, crs: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(df.copy(), geometry=[Point(x, y) for x, y in zip(df[lon_col], df[lat_col])], crs=crs)


def point_geojson_from_projected(df: pd.DataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        df.copy(),
        geometry=[Point(x, y) for x, y in zip(df["x_epsg32650"], df["y_epsg32650"])],
        crs=TARGET_CRS,
    )


def convert_coords_gcj_list_to_wgs(coords: list) -> list:
    out = []
    for item in coords:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], (float, int)):
            lon, lat = gcj02_to_wgs84(float(item[0]), float(item[1]))
            out.append([lon, lat])
        elif isinstance(item, list):
            out.append(convert_coords_gcj_list_to_wgs(item))
        else:
            out.append(item)
    return out


def validate_required_columns(df: pd.DataFrame, columns: list[str], label: str) -> list[dict[str, Any]]:
    rows = []
    for col in columns:
        if col not in df.columns:
            rows.append({"dataset": label, "check": f"missing_column:{col}", "severity": "error", "count": ""})
        else:
            missing = int(df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum())
            if missing:
                rows.append({"dataset": label, "check": f"blank_values:{col}", "severity": "error", "count": missing})
    return rows


def add_bus_validation(
    qa_rows: list[dict[str, Any]],
    df: pd.DataFrame,
    label: str,
    transformer: Transformer,
    warn_threshold_m: float = 2.0,
) -> None:
    required = ["lon_gcj02", "lat_gcj02", "lon_wgs84", "lat_wgs84", "x_epsg32650", "y_epsg32650"]
    qa_rows.extend(validate_required_columns(df, required, label))
    if any(col not in df.columns for col in required):
        return
    lon = float_series(df, "lon_wgs84")
    lat = float_series(df, "lat_wgs84")
    x_stored = float_series(df, "x_epsg32650")
    y_stored = float_series(df, "y_epsg32650")
    x_calc, y_calc = transformer.transform(lon.to_numpy(), lat.to_numpy())
    diff = ((x_calc - x_stored.to_numpy()) ** 2 + (y_calc - y_stored.to_numpy()) ** 2) ** 0.5
    finite = diff[~pd.isna(diff)]
    if len(finite):
        qa_rows.append(
            {
                "dataset": label,
                "check": "epsg32650_reprojection_diff_m",
                "severity": "info" if float(finite.max()) <= warn_threshold_m else "warning",
                "count": int((finite > warn_threshold_m).sum()),
                "max_value": float(finite.max()),
                "mean_value": float(finite.mean()),
            }
        )


def write_bus_outputs(out_dir: pathlib.Path, qa_rows: list[dict[str, Any]], transformer: Transformer) -> dict[str, int]:
    bus_dir = out_dir / "bus"
    counts: dict[str, int] = {}

    stops = pd.read_csv(BUS_STOPS, encoding="utf-8-sig")
    stops["mode"] = "bus"
    stops["coord_source"] = "AMap GCJ-02 converted to WGS84/EPSG:32650 in source final dataset"
    add_bus_validation(qa_rows, stops, "bus_stops_complete", transformer)
    stops.to_csv(bus_dir / "bus_stops_unified.csv", index=False, encoding="utf-8-sig")
    point_geojson_from_xy(stops, "lon_wgs84", "lat_wgs84", WGS84).to_file(bus_dir / "bus_stops_unified_wgs84.geojson", driver="GeoJSON")
    point_geojson_from_projected(stops).to_file(bus_dir / "bus_stops_unified_epsg32650.geojson", driver="GeoJSON")
    counts["bus_stops"] = len(stops)

    stops_by_line = pd.read_csv(BUS_STOPS_BY_LINE, encoding="utf-8-sig")
    stops_by_line["mode"] = "bus"
    stops_by_line["coord_source"] = "AMap GCJ-02 converted to WGS84/EPSG:32650 in source final dataset"
    add_bus_validation(qa_rows, stops_by_line, "bus_stops_by_line", transformer)
    stops_by_line.to_csv(bus_dir / "bus_stops_by_line_unified.csv", index=False, encoding="utf-8-sig")
    counts["bus_stops_by_line"] = len(stops_by_line)

    bus_traj_wgs = read_geojson(BUS_TRAJECTORIES)
    for feature in bus_traj_wgs.get("features", []):
        props = feature.setdefault("properties", {})
        props["mode"] = "bus"
        props["coord_source"] = props.get("coord_source") or "AMap GCJ-02 converted to WGS84 in source final dataset"
        props["crs"] = WGS84
    write_geojson(bus_dir / "bus_line_trajectories_wgs84.geojson", bus_traj_wgs)

    gdf_wgs = gpd.read_file(bus_dir / "bus_line_trajectories_wgs84.geojson")
    if gdf_wgs.crs is None:
        gdf_wgs = gdf_wgs.set_crs(WGS84)
    gdf_epsg = gdf_wgs.to_crs(TARGET_CRS)
    gdf_epsg["coord_source"] = "WGS84 bus trajectory projected to EPSG:32650; no second GCJ correction"
    gdf_epsg.to_file(bus_dir / "bus_line_trajectories_epsg32650.geojson", driver="GeoJSON")
    counts["bus_line_trajectories"] = len(gdf_wgs)
    return counts


def convert_metro_points(df: pd.DataFrame, lon_col: str = "lon", lat_col: str = "lat") -> pd.DataFrame:
    transformer = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    out = df.copy()
    lon_gcj = float_series(out, lon_col)
    lat_gcj = float_series(out, lat_col)
    converted = [gcj02_to_wgs84(float(lon), float(lat)) for lon, lat in zip(lon_gcj, lat_gcj)]
    out["lon_gcj02"] = lon_gcj
    out["lat_gcj02"] = lat_gcj
    out["lon_wgs84"] = [p[0] for p in converted]
    out["lat_wgs84"] = [p[1] for p in converted]
    x, y = transformer.transform(out["lon_wgs84"].to_numpy(), out["lat_wgs84"].to_numpy())
    out["x_epsg32650"] = x
    out["y_epsg32650"] = y
    out["coord_source"] = "AMap GCJ-02 converted to WGS84/EPSG:32650 by coordinate unification"
    return out


def write_metro_outputs(out_dir: pathlib.Path, qa_rows: list[dict[str, Any]]) -> dict[str, int]:
    metro_dir = out_dir / "metro"
    counts: dict[str, int] = {}

    stations = pd.read_csv(METRO_STATIONS, encoding="utf-8-sig")
    stations = convert_metro_points(stations)
    stations["mode"] = "metro"
    qa_rows.extend(validate_required_columns(stations, ["lon_wgs84", "lat_wgs84", "x_epsg32650", "y_epsg32650"], "metro_stations"))
    stations.to_csv(metro_dir / "metro_stations_unified.csv", index=False, encoding="utf-8-sig")
    point_geojson_from_xy(stations, "lon_wgs84", "lat_wgs84", WGS84).to_file(metro_dir / "metro_stations_unified_wgs84.geojson", driver="GeoJSON")
    point_geojson_from_projected(stations).to_file(metro_dir / "metro_stations_unified_epsg32650.geojson", driver="GeoJSON")
    counts["metro_stations"] = len(stations)

    stops_by_line = pd.read_csv(METRO_STOPS_BY_LINE, encoding="utf-8-sig")
    stops_by_line = convert_metro_points(stops_by_line)
    stops_by_line["mode"] = "metro"
    qa_rows.extend(
        validate_required_columns(stops_by_line, ["lon_wgs84", "lat_wgs84", "x_epsg32650", "y_epsg32650"], "metro_stops_by_line")
    )
    stops_by_line.to_csv(metro_dir / "metro_stops_by_line_unified.csv", index=False, encoding="utf-8-sig")
    counts["metro_stops_by_line"] = len(stops_by_line)

    metro_gcj = read_geojson(METRO_TRAJECTORIES)
    metro_wgs = {"type": "FeatureCollection", "features": []}
    for feature in metro_gcj.get("features", []):
        geom = feature.get("geometry")
        new_feature = {"type": "Feature", "properties": dict(feature.get("properties", {})), "geometry": None}
        if geom:
            new_geom = dict(geom)
            new_geom["coordinates"] = convert_coords_gcj_list_to_wgs(new_geom.get("coordinates", []))
            new_feature["geometry"] = new_geom
        new_feature["properties"]["mode"] = "metro"
        new_feature["properties"]["coord_source"] = "AMap GCJ-02 converted to WGS84 by coordinate unification"
        new_feature["properties"]["crs"] = WGS84
        metro_wgs["features"].append(new_feature)
    write_geojson(metro_dir / "metro_line_trajectories_wgs84.geojson", metro_wgs)

    gdf_wgs = gpd.read_file(metro_dir / "metro_line_trajectories_wgs84.geojson")
    if gdf_wgs.crs is None:
        gdf_wgs = gdf_wgs.set_crs(WGS84)
    gdf_epsg = gdf_wgs.to_crs(TARGET_CRS)
    gdf_epsg["coord_source"] = "AMap GCJ-02 converted to WGS84, then projected to EPSG:32650"
    gdf_epsg.to_file(metro_dir / "metro_line_trajectories_epsg32650.geojson", driver="GeoJSON")
    counts["metro_line_trajectories"] = len(gdf_wgs)
    return counts


def write_combined_outputs(out_dir: pathlib.Path, counts: dict[str, int]) -> dict[str, int]:
    combined_dir = out_dir / "combined"
    bus = pd.read_csv(out_dir / "bus" / "bus_stops_unified.csv", encoding="utf-8-sig")
    metro = pd.read_csv(out_dir / "metro" / "metro_stations_unified.csv", encoding="utf-8-sig")

    bus_combined = pd.DataFrame(
        {
            "mode": "bus",
            "stop_id": bus["merged_stop_id"],
            "source_ids": bus.get("source_ids", ""),
            "name": bus["name"],
            "lon_gcj02": bus["lon_gcj02"],
            "lat_gcj02": bus["lat_gcj02"],
            "lon_wgs84": bus["lon_wgs84"],
            "lat_wgs84": bus["lat_wgs84"],
            "x_epsg32650": bus["x_epsg32650"],
            "y_epsg32650": bus["y_epsg32650"],
            "line_ids": bus.get("line_ids", ""),
            "coord_source": bus["coord_source"],
        }
    )
    metro_combined = pd.DataFrame(
        {
            "mode": "metro",
            "stop_id": metro["station_id"],
            "source_ids": metro["amap_stop_id"],
            "name": metro["station_name"],
            "lon_gcj02": metro["lon_gcj02"],
            "lat_gcj02": metro["lat_gcj02"],
            "lon_wgs84": metro["lon_wgs84"],
            "lat_wgs84": metro["lat_wgs84"],
            "x_epsg32650": metro["x_epsg32650"],
            "y_epsg32650": metro["y_epsg32650"],
            "line_ids": metro.get("line_ids", ""),
            "coord_source": metro["coord_source"],
        }
    )
    combined = pd.concat([bus_combined, metro_combined], ignore_index=True)
    combined.to_csv(combined_dir / "transit_stops_unified.csv", index=False, encoding="utf-8-sig")
    point_geojson_from_xy(combined, "lon_wgs84", "lat_wgs84", WGS84).to_file(
        combined_dir / "transit_stops_unified_wgs84.geojson", driver="GeoJSON"
    )
    point_geojson_from_projected(combined).to_file(combined_dir / "transit_stops_unified_epsg32650.geojson", driver="GeoJSON")
    counts["combined_transit_stops"] = len(combined)
    return counts


def write_preview(out_dir: pathlib.Path) -> pathlib.Path:
    vis_dir = out_dir / "visualization"
    font_path = pathlib.Path("C:/Windows/Fonts/msyh.ttc")
    font_prop = None
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        font_prop = fm.FontProperties(fname=str(font_path))
        plt.rcParams["font.family"] = font_prop.get_name()
        plt.rcParams["axes.unicode_minus"] = False

    bus_lines = gpd.read_file(out_dir / "bus" / "bus_line_trajectories_epsg32650.geojson")
    metro_lines = gpd.read_file(out_dir / "metro" / "metro_line_trajectories_epsg32650.geojson")
    bus_stops = gpd.read_file(out_dir / "bus" / "bus_stops_unified_epsg32650.geojson")
    metro_stations = gpd.read_file(out_dir / "metro" / "metro_stations_unified_epsg32650.geojson")

    fig, ax = plt.subplots(figsize=(12, 10), dpi=180)
    bus_lines.plot(ax=ax, linewidth=0.25, color="#9ca3af", alpha=0.35, label="公交线路")
    metro_lines.plot(ax=ax, linewidth=2.0, color="#2563eb", alpha=0.9, label="地铁线路")
    bus_stops.plot(ax=ax, markersize=0.8, color="#111827", alpha=0.35, label="公交站")
    metro_stations.plot(ax=ax, markersize=18, color="#ef4444", alpha=0.95, label="地铁站")
    ax.set_title("福州公交/地铁统一坐标预览（EPSG:32650）", fontsize=14)
    ax.set_axis_off()
    if font_prop:
        ax.legend(loc="best", fontsize=8, prop=font_prop)
    else:
        ax.legend(loc="best", fontsize=8)
    plt.tight_layout()
    out_path = vis_dir / "unified_bus_metro_epsg32650_preview.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def write_manifest(out_dir: pathlib.Path) -> int:
    rows = []
    for path in sorted(out_dir.rglob("*")):
        if path.is_file():
            rows.append(
                {
                    "relative_path": path.relative_to(out_dir).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "modified_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
    with (out_dir / "metadata" / "final_file_manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relative_path", "size_bytes", "modified_time"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_quality_report(out_dir: pathlib.Path, qa_rows: list[dict[str, Any]]) -> int:
    fields = sorted({key for row in qa_rows for key in row.keys()} | {"dataset", "check", "severity", "count", "max_value", "mean_value"})
    with (out_dir / "metadata" / "coordinate_quality_report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(qa_rows)
    return len(qa_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unify Fuzhou bus/metro coordinates for MATSim.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Output directory.")
    parser.add_argument("--overwrite", action="store_true", help="Remove the output directory before writing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = pathlib.Path(args.output_dir)
    if out_dir.exists() and args.overwrite:
        shutil.rmtree(out_dir)
    ensure_dirs(out_dir)

    qa_rows: list[dict[str, Any]] = []
    transformer_4326_to_32650 = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)

    counts: dict[str, int] = {}
    counts.update(write_bus_outputs(out_dir, qa_rows, transformer_4326_to_32650))
    counts.update(write_metro_outputs(out_dir, qa_rows))
    counts.update(write_combined_outputs(out_dir, counts))
    preview_path = write_preview(out_dir)

    quality_rows = write_quality_report(out_dir, qa_rows)
    manifest_count = write_manifest(out_dir)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out_dir),
        "target_crs": TARGET_CRS,
        "wgs84": WGS84,
        "coordinate_policy": {
            "bus_stop_tables": "copy validated existing GCJ-02/WGS84/EPSG:32650 coordinates from final bus dataset",
            "bus_trajectories": "source GeoJSON is already WGS84; project only to EPSG:32650, no second GCJ correction",
            "metro_tables": "treat lon/lat as GCJ-02; convert to WGS84 and EPSG:32650",
            "metro_trajectories": "treat GeoJSON coordinates as GCJ-02; convert to WGS84 and EPSG:32650",
        },
        "counts": counts,
        "quality_report_rows": quality_rows,
        "manifest_file_count": manifest_count,
        "visualization": str(preview_path),
        "source_inputs": {
            "bus_stops": str(BUS_STOPS),
            "bus_stops_by_line": str(BUS_STOPS_BY_LINE),
            "bus_trajectories": str(BUS_TRAJECTORIES),
            "metro_stations": str(METRO_STATIONS),
            "metro_stops_by_line": str(METRO_STOPS_BY_LINE),
            "metro_trajectories": str(METRO_TRAJECTORIES),
        },
    }
    (out_dir / "metadata" / "coordinate_unification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Refresh manifest after summary creation.
    summary["manifest_file_count"] = write_manifest(out_dir)
    (out_dir / "metadata" / "coordinate_unification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
