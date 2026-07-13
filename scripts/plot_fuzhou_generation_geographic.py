"""Create geographic OD-flow visualizations for the Greenspace Fuzhou grid.

Inputs:
  - generation.npy: OD matrix
  - regions.shp: custom Greenspace Fuzhou grid polygons

Outputs:
  - geographic flow PNG
  - top-flow LineString GeoJSON
  - centroid GeoJSON
  - summary JSON
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = pathlib.Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REGIONS = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "CityAndRegionSplit"
    / "fuzhou_city_23_greenspace_grid"
    / "regions.shp"
)
DEFAULT_GENERATION = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "CommutingODFlows"
    / "fuzhou_city_23_greenspace_grid"
    / "generation.npy"
)
DEFAULT_OUT_DIR = DEFAULT_GENERATION.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot geographic OD flows for Fuzhou Greenspace grid.")
    parser.add_argument("--regions", default=str(DEFAULT_REGIONS), help="Grid regions shapefile.")
    parser.add_argument("--generation", default=str(DEFAULT_GENERATION), help="OD generation.npy.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--top-n-plot", type=int, default=5000, help="Number of top OD flows to draw in PNG.")
    parser.add_argument("--top-n-geojson", type=int, default=20000, help="Number of top OD flows to export as GeoJSON.")
    parser.add_argument("--min-flow", type=float, default=1.0, help="Ignore OD flows below this value.")
    parser.add_argument("--dpi", type=int, default=220, help="PNG DPI.")
    parser.add_argument("--with-basemap", action="store_true", help="Try to add a contextily basemap if installed/network works.")
    return parser.parse_args()


def top_od_pairs(od: np.ndarray, top_n: int, min_flow: float) -> pd.DataFrame:
    mask = (od >= min_flow) & (~np.eye(od.shape[0], dtype=bool))
    origins, destinations = np.where(mask)
    flows = od[origins, destinations]
    if len(flows) == 0:
        return pd.DataFrame(columns=["origin", "destination", "flow"])
    order = np.argsort(flows)[::-1]
    if top_n is not None:
        order = order[: min(top_n, len(order))]
    return pd.DataFrame(
        {
            "origin": origins[order].astype(int),
            "destination": destinations[order].astype(int),
            "flow": flows[order].astype(float),
        }
    )


def make_flow_gdf(pairs: pd.DataFrame, centroids: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    records = []
    geoms = []
    locations = centroids["locations"].astype(str).tolist() if "locations" in centroids.columns else [str(i) for i in range(len(centroids))]
    for _, row in pairs.iterrows():
        o = int(row["origin"])
        d = int(row["destination"])
        p0 = centroids.geometry.iloc[o]
        p1 = centroids.geometry.iloc[d]
        if p0.is_empty or p1.is_empty:
            continue
        geoms.append(LineString([p0, p1]))
        records.append(
            {
                "origin": o,
                "destination": d,
                "origin_loc": locations[o],
                "dest_loc": locations[d],
                "flow": float(row["flow"]),
            }
        )
    return gpd.GeoDataFrame(records, geometry=geoms, crs=crs)


def save_static_png(regions: gpd.GeoDataFrame, flows: gpd.GeoDataFrame, png_path: pathlib.Path, dpi: int, with_basemap: bool) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable

    regions_3857 = regions.to_crs("EPSG:3857")
    flows_3857 = flows.to_crs("EPSG:3857")

    fig, ax = plt.subplots(figsize=(9, 7), dpi=dpi)
    regions_3857.plot(ax=ax, facecolor="#f7f7f7", edgecolor="#9e9e9e", linewidth=0.18, alpha=0.72)

    if len(flows_3857) > 0:
        flows_sorted = flows_3857.sort_values("flow")
        flow = flows_sorted["flow"].to_numpy()
        q05, q95 = np.quantile(flow, [0.05, 0.95]) if len(flow) > 1 else (flow.min(), flow.max())
        denom = max(q95 - q05, 1.0)
        linewidth = 0.08 + 1.2 * np.clip((flow - q05) / denom, 0, 1)
        alpha = 0.08 + 0.45 * np.clip((flow - q05) / denom, 0, 1)
        norm = Normalize(vmin=float(flow.min()), vmax=float(flow.max()))
        flows_sorted.plot(
            ax=ax,
            column="flow",
            cmap="plasma",
            linewidth=linewidth,
            alpha=alpha,
            legend=False,
        )
        sm = ScalarMappable(norm=norm, cmap="plasma")
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, shrink=0.78, pad=0.01)
        cbar.set_label("OD flow")

    if with_basemap:
        try:
            import contextily as cx

            cx.add_basemap(ax, crs=regions_3857.crs, source=cx.providers.CartoDB.Positron, alpha=0.72)
        except Exception as exc:
            print(f"Basemap skipped: {exc}")

    minx, miny, maxx, maxy = regions_3857.total_bounds
    dx = (maxx - minx) * 0.04
    dy = (maxy - miny) * 0.04
    ax.set_xlim(minx - dx, maxx + dx)
    ax.set_ylim(miny - dy, maxy + dy)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(f"Fuzhou Greenspace Grid OD Flows (top {len(flows):,})", fontsize=12)
    fig.tight_layout()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    regions_path = pathlib.Path(args.regions)
    generation_path = pathlib.Path(args.generation)
    out_dir = pathlib.Path(args.out_dir)
    for path in [regions_path, generation_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    out_dir.mkdir(parents=True, exist_ok=True)
    regions = gpd.read_file(regions_path).reset_index(drop=True)
    od = np.load(generation_path)
    if od.shape[0] != od.shape[1] or od.shape[0] != len(regions):
        raise ValueError(f"OD shape {od.shape} does not match regions count {len(regions)}")

    centroids = regions.copy()
    centroids["geometry"] = regions.geometry.centroid
    centroids["grid_index"] = np.arange(len(centroids), dtype=int)

    pairs_plot = top_od_pairs(od, args.top_n_plot, args.min_flow)
    pairs_geojson = top_od_pairs(od, args.top_n_geojson, args.min_flow)
    flows_plot = make_flow_gdf(pairs_plot, centroids, regions.crs)
    flows_geojson = make_flow_gdf(pairs_geojson, centroids, regions.crs)

    png_path = out_dir / "generation_geographic_top5000.png"
    flows_geojson_path = out_dir / f"generation_top{args.top_n_geojson}_flows.geojson"
    flows_plot_geojson_path = out_dir / f"generation_top{args.top_n_plot}_flows.geojson"
    centroids_path = out_dir / "generation_grid_centroids.geojson"
    summary_path = out_dir / "generation_geographic_summary.json"

    save_static_png(regions, flows_plot, png_path, args.dpi, args.with_basemap)
    flows_geojson.to_crs("EPSG:4326").to_file(flows_geojson_path, driver="GeoJSON")
    flows_plot.to_crs("EPSG:4326").to_file(flows_plot_geojson_path, driver="GeoJSON")
    centroids.to_crs("EPSG:4326").to_file(centroids_path, driver="GeoJSON")

    nonzero = od[(od > 0) & (~np.eye(od.shape[0], dtype=bool))]
    summary = {
        "regions": str(regions_path),
        "generation": str(generation_path),
        "od_shape": list(od.shape),
        "od_sum": float(od.sum()),
        "nonzero_od_pairs": int(len(nonzero)),
        "max_flow": float(od.max()),
        "min_flow_filter": args.min_flow,
        "plot_top_n": int(len(flows_plot)),
        "geojson_top_n": int(len(flows_geojson)),
        "png": str(png_path),
        "top_plot_geojson": str(flows_plot_geojson_path),
        "top_geojson": str(flows_geojson_path),
        "centroids_geojson": str(centroids_path),
        "flow_quantiles": {
            "q50": float(np.quantile(nonzero, 0.50)) if len(nonzero) else 0.0,
            "q90": float(np.quantile(nonzero, 0.90)) if len(nonzero) else 0.0,
            "q95": float(np.quantile(nonzero, 0.95)) if len(nonzero) else 0.0,
            "q99": float(np.quantile(nonzero, 0.99)) if len(nonzero) else 0.0,
        },
        "note": "Geographic flow lines connect origin/destination grid centroids. Only top flows are exported/drawn to keep the map readable.",
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {png_path}")
    print(f"Wrote: {flows_plot_geojson_path}")
    print(f"Wrote: {flows_geojson_path}")
    print(f"Wrote: {centroids_path}")
    print(f"Wrote: {summary_path}")
    print(f"OD sum: {summary['od_sum']:.0f}; nonzero pairs: {summary['nonzero_od_pairs']}; max flow: {summary['max_flow']:.0f}")


if __name__ == "__main__":
    main()
