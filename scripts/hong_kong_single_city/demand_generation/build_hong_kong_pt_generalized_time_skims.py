#!/usr/bin/env python3
"""Build six-period SwissRailRaptor skims for Hong Kong grids and control points."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
WORK_CRS = "EPSG:32650"
DEFAULT_TIMES = ("07:00", "10:00", "13:00", "17:00", "20:00", "22:00")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--supply-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--times", default=",".join(DEFAULT_TIMES))
    parser.add_argument("--skip-java", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--keep-raw", action="store_true")
    parser.add_argument("--maven", type=Path, default=ROOT / "mvnw.cmd")
    return parser.parse_args()


def default_paths(data_root: Path) -> tuple[Path, Path, Path, Path]:
    city = data_root / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    grid = city / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
    old_model = data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday"
    control_points = old_model / "model_control_points_14.csv"
    supply = (
        data_root
        / "transit/hongkong/processed"
        / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
    )
    output = data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday_pt_access_v2"
    return grid, control_points, supply, output


def prepare_nodes(grid_path: Path, control_points_path: Path, out_dir: Path) -> pd.DataFrame:
    grid = gpd.read_file(grid_path).to_crs(WORK_CRS).reset_index(drop=True)
    if len(grid) != 1585:
        raise ValueError(f"Expected 1,585 grids, found {len(grid)}")
    centroids = grid.geometry.centroid
    grid_nodes = pd.DataFrame({
        "node_index": np.arange(len(grid), dtype=int),
        "node_id": [f"grid_{index}" for index in range(len(grid))],
        "node_type": "grid",
        "x": centroids.x.to_numpy(),
        "y": centroids.y.to_numpy(),
        "grid_index": np.arange(len(grid), dtype=int),
        "bcp_index": pd.Series([pd.NA] * len(grid), dtype="Int64"),
        "label": grid.get("locations", pd.Series(np.arange(len(grid)).astype(str))).astype(str),
    })

    ports = pd.read_csv(control_points_path, encoding="utf-8-sig")
    if len(ports) != 14 or ports["bcp_index"].tolist() != list(range(14)):
        raise ValueError("Control-point table must contain bcp_index 0..13")
    port_geo = gpd.GeoDataFrame(
        ports,
        geometry=gpd.points_from_xy(ports.longitude, ports.latitude),
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)
    port_nodes = pd.DataFrame({
        "node_index": len(grid) + ports.bcp_index.to_numpy(dtype=int),
        "node_id": [f"bcp_{index}" for index in ports.bcp_index],
        "node_type": "control_point",
        "x": port_geo.geometry.x.to_numpy(),
        "y": port_geo.geometry.y.to_numpy(),
        "grid_index": pd.Series([pd.NA] * len(ports), dtype="Int64"),
        "bcp_index": ports.bcp_index.astype("Int64"),
        "label": ports.control_point.astype(str),
    })
    nodes = pd.concat([grid_nodes, port_nodes], ignore_index=True)
    nodes.to_csv(out_dir / "skim_nodes.csv", index=False, encoding="utf-8-sig")
    nodes[["node_index", "node_id", "node_type", "x", "y"]].to_csv(
        out_dir / "skim_nodes.tsv", sep="\t", index=False, encoding="utf-8", lineterminator="\n"
    )
    return nodes


def run_java(
    maven: Path,
    supply_dir: Path,
    nodes_path: Path,
    raw_dir: Path,
    times: list[str],
) -> None:
    required = [
        supply_dir / "network.xml.gz",
        supply_dir / "transitSchedule.xml.gz",
        supply_dir / "transitVehicles.xml.gz",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    def quote(path: Path) -> str:
        return f'"{str(path).replace(chr(34), chr(92) + chr(34))}"'

    exec_args = " ".join(quote(path.resolve()) for path in [*required, nodes_path, raw_dir])
    exec_args += " " + ",".join(times)
    command = [
        str(maven),
        "-q",
        "-DskipTests",
        "compile",
        "exec:java",
        "-Dexec.mainClass=org.matsim.project.BuildHongKongPtSkims",
        f"-Dexec.args={exec_args}",
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def read_raw_array(path: Path, dtype: str, shape: tuple[int, int]) -> np.ndarray:
    expected = int(np.prod(shape)) * np.dtype(dtype).itemsize
    if not path.exists() or path.stat().st_size != expected:
        actual = path.stat().st_size if path.exists() else None
        raise ValueError(f"Unexpected binary size for {path}: expected {expected}, found {actual}")
    return np.memmap(path, mode="r", dtype=dtype, shape=shape)


def package_skims(raw_dir: Path, out_dir: Path, nodes: pd.DataFrame, times: list[str]) -> dict[str, object]:
    count = len(nodes)
    shape = (count, count)
    travel = []
    generalized = []
    transfers = []
    reachable = []
    for time_value in times:
        slug = time_value.replace(":", "")
        travel.append(np.asarray(read_raw_array(raw_dir / f"travel_time_{slug}.f32", "<f4", shape)))
        generalized.append(np.asarray(read_raw_array(raw_dir / f"generalized_time_{slug}.f32", "<f4", shape)))
        transfers.append(np.asarray(read_raw_array(raw_dir / f"transfers_{slug}.i16", "<i2", shape)))
        reachable.append(np.asarray(read_raw_array(raw_dir / f"reachable_{slug}.u8", "u1", shape)))
    travel_array = np.stack(travel)
    generalized_array = np.stack(generalized)
    transfer_array = np.stack(transfers)
    reachable_array = np.stack(reachable).astype(bool)
    if travel_array.shape != (len(times), 1599, 1599):
        raise ValueError(f"Unexpected skim shape {travel_array.shape}")
    diagonal = np.arange(count)
    if not np.all(travel_array[:, diagonal, diagonal] == 0):
        raise ValueError("Travel-time skim diagonal is not zero")
    if not np.array_equal(np.isfinite(generalized_array), reachable_array):
        raise ValueError("Reachability and generalized-time finiteness disagree")

    np.savez_compressed(
        out_dir / "pt_generalized_time_skims.npz",
        departure_times=np.asarray(times),
        travel_time_seconds=travel_array,
        generalized_time_seconds=generalized_array,
        transfers=transfer_array,
        reachable=reachable_array,
        node_index=nodes.node_index.to_numpy(dtype=np.int32),
        node_id=nodes.node_id.to_numpy(dtype=str),
        node_type=nodes.node_type.to_numpy(dtype=str),
    )
    access = pd.read_csv(raw_dir / "node_stop_access.tsv", sep="\t")
    access.to_csv(out_dir / "node_stop_access.csv", index=False, encoding="utf-8-sig")
    port_access = access[access.node_type.eq("control_point")].copy()
    port_access.to_csv(out_dir / "control_point_stop_access_audit.csv", index=False, encoding="utf-8-sig")

    finite = generalized_array[np.isfinite(generalized_array) & (generalized_array > 0)]
    summary: dict[str, object] = {
        "node_count": count,
        "grid_count": int((nodes.node_type == "grid").sum()),
        "control_point_count": int((nodes.node_type == "control_point").sum()),
        "departure_times": times,
        "shape": list(generalized_array.shape),
        "reachable_share": float(reachable_array.mean()),
        "generalized_time_minutes_p50": float(np.median(finite) / 60.0),
        "generalized_time_minutes_p95": float(np.quantile(finite, 0.95) / 60.0),
        "control_point_nearest_stop_max_m": float(
            port_access.loc[port_access.access_rank.eq(1), "distance_m"].max()
        ),
        "weights": {
            "in_vehicle": 1.0,
            "waiting": 2.0,
            "walking": 2.0,
            "transfer_penalty_seconds": 300.0,
        },
        "unreachable_policy": "NaN; no Euclidean-distance fallback",
    }
    (out_dir / "pt_skim_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    args = parse_args()
    grid_path, control_points_path, default_supply, default_output = default_paths(args.data_root)
    supply_dir = args.supply_dir or default_supply
    out_dir = args.out_dir or default_output
    raw_dir = out_dir / "pt_skim_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(exist_ok=True)
    times = [value.strip() for value in args.times.split(",") if value.strip()]
    if times != list(DEFAULT_TIMES):
        raise ValueError(f"The formal scenario requires times {DEFAULT_TIMES}, found {times}")
    for path in [grid_path, control_points_path]:
        if not path.exists():
            raise FileNotFoundError(path)
    nodes = prepare_nodes(grid_path, control_points_path, out_dir)
    if args.prepare_only:
        print(json.dumps({"prepared_nodes": len(nodes), "output": str(out_dir)}, ensure_ascii=False, indent=2))
        return
    if not args.skip_java:
        run_java(args.maven, supply_dir, out_dir / "skim_nodes.tsv", raw_dir, times)
    summary = package_skims(raw_dir, out_dir, nodes, times)
    if not args.keep_raw:
        for path in raw_dir.glob("*.f32"):
            path.unlink()
        for path in raw_dir.glob("*.i16"):
            path.unlink()
        for path in raw_dir.glob("*.u8"):
            path.unlink()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
