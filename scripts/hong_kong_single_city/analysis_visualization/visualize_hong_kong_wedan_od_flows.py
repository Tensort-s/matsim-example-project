#!/usr/bin/env python3
"""Visualize Hong Kong WEDAN OD flows on the fixed-link city boundary."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from shapely.geometry import LineString


matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection


ROOT = Path(__file__).resolve().parents[3]
CITY_NAME = "hong_kong_fixed_link_grid"
MODEL_CRS = "EPSG:32650"
DEFAULT_BOUNDARY = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
DEFAULT_BOUNDARY_SIMPLIFIED = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84_simplified.geojson"
DEFAULT_GRID = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
DEFAULT_OD = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CommutingODFlows/hong_kong_fixed_link_grid/generation.npy"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CommutingODFlows/hong_kong_fixed_link_grid/visualization"
)
DEFAULT_INLINE_HTML = (
    Path.home()
    / ".codex/visualizations/2026/07/14/019f6021-ca91-78f3-b0b0-a05f2177732a/hong-kong-od-flows.html"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY, help="Hong Kong fixed-link boundary GeoJSON.")
    parser.add_argument("--boundary-simplified", type=Path, default=DEFAULT_BOUNDARY_SIMPLIFIED, help="Simplified boundary for inline HTML.")
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID, help="Hong Kong fixed-link grid regions.shp.")
    parser.add_argument("--od", type=Path, default=DEFAULT_OD, help="WEDAN generation.npy.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Visualization output directory.")
    parser.add_argument("--top-k", type=int, default=800, help="Number of highest OD flows to draw in the static map.")
    parser.add_argument("--html-top-k", type=int, default=300, help="Number of highest OD flows embedded in the inline HTML.")
    parser.add_argument("--inline-html", type=Path, default=DEFAULT_INLINE_HTML, help="Optional Codex inline visualization HTML fragment.")
    return parser.parse_args()


def top_od_pairs(od: np.ndarray, top_k: int) -> pd.DataFrame:
    if od.ndim != 2 or od.shape[0] != od.shape[1]:
        raise ValueError(f"OD matrix must be square, got {od.shape}")
    n = od.shape[0]
    flat = od.ravel().astype("float64", copy=True)
    flat[np.arange(n) * n + np.arange(n)] = -np.inf
    finite_positive = np.flatnonzero(np.isfinite(flat) & (flat > 0))
    if len(finite_positive) == 0:
        raise ValueError("OD matrix has no positive off-diagonal flows.")
    k = min(top_k, len(finite_positive))
    candidate = finite_positive[np.argpartition(flat[finite_positive], -k)[-k:]]
    candidate = candidate[np.argsort(flat[candidate])[::-1]]
    origins = candidate // n
    destinations = candidate % n
    return pd.DataFrame(
        {
            "rank": np.arange(1, len(candidate) + 1, dtype=int),
            "origin_index": origins.astype(int),
            "destination_index": destinations.astype(int),
            "flow": flat[candidate].astype(float),
        }
    )


def build_flow_layers(grid: gpd.GeoDataFrame, od: np.ndarray, top_k: int) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    pairs = top_od_pairs(od, top_k)
    grid_metric = grid.to_crs(MODEL_CRS).reset_index(drop=True)
    cent_metric = grid_metric.geometry.centroid
    cent_wgs84 = gpd.GeoSeries(cent_metric, crs=MODEL_CRS).to_crs("EPSG:4326")

    outflow = od.sum(axis=1)
    inflow = od.sum(axis=0)
    grid_totals = grid.drop(columns="geometry").copy()
    grid_totals["outflow"] = outflow
    grid_totals["inflow"] = inflow
    grid_totals["net_outflow"] = outflow - inflow

    records: list[dict] = []
    geometries = []
    for row in pairs.itertuples(index=False):
        oi = int(row.origin_index)
        di = int(row.destination_index)
        line = LineString([(cent_metric.iloc[oi].x, cent_metric.iloc[oi].y), (cent_metric.iloc[di].x, cent_metric.iloc[di].y)])
        geometries.append(line)
        records.append(
            {
                "rank": int(row.rank),
                "origin_index": oi,
                "destination_index": di,
                "origin_grid_id": int(grid.iloc[oi].get("grid_id", oi)),
                "destination_grid_id": int(grid.iloc[di].get("grid_id", di)),
                "origin_locations": str(grid.iloc[oi].get("locations", oi)),
                "destination_locations": str(grid.iloc[di].get("locations", di)),
                "flow": float(row.flow),
                "origin_lon": float(cent_wgs84.iloc[oi].x),
                "origin_lat": float(cent_wgs84.iloc[oi].y),
                "destination_lon": float(cent_wgs84.iloc[di].x),
                "destination_lat": float(cent_wgs84.iloc[di].y),
            }
        )
    flows = gpd.GeoDataFrame(records, geometry=geometries, crs=MODEL_CRS)
    return flows, grid_totals


def save_static_map(boundary_path: Path, flows: gpd.GeoDataFrame, out_path: Path) -> None:
    boundary = gpd.read_file(boundary_path).to_crs(MODEL_CRS)
    flows_metric = flows.to_crs(MODEL_CRS)
    flow_values = flows_metric["flow"].to_numpy(dtype="float64")
    log_flow = np.log1p(flow_values)
    denom = max(log_flow.max() - log_flow.min(), 1.0)
    widths = 0.15 + 2.8 * (log_flow - log_flow.min()) / denom
    alphas = 0.12 + 0.58 * (log_flow - log_flow.min()) / denom
    segments = [[(x, y) for x, y in line.coords] for line in flows_metric.geometry]

    fig, ax = plt.subplots(figsize=(11, 8), dpi=220)
    boundary.plot(ax=ax, facecolor="#f3f1e8", edgecolor="#404040", linewidth=0.45)
    lc = LineCollection(segments, linewidths=widths, colors="#cf3f2d", zorder=5)
    lc.set_alpha(alphas)
    ax.add_collection(lc)

    top = flows_metric.iloc[:25]
    ax.scatter(top.geometry.apply(lambda g: g.coords[0][0]), top.geometry.apply(lambda g: g.coords[0][1]), s=9, c="#2458a6", alpha=0.55, zorder=6, label="Top origins")
    ax.scatter(top.geometry.apply(lambda g: g.coords[-1][0]), top.geometry.apply(lambda g: g.coords[-1][1]), s=9, c="#111111", alpha=0.45, zorder=6, label="Top destinations")

    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(f"Hong Kong fixed-link WEDAN OD flows: top {len(flows_metric):,}", fontsize=13)
    ax.text(
        0.01,
        0.02,
        f"Line width encodes log1p(flow). Max top-flow value: {flow_values.max():.0f}",
        transform=ax.transAxes,
        fontsize=8.5,
        color="#333333",
    )
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    fig.tight_layout(pad=0.2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def compact_boundary(boundary_path: Path) -> dict:
    boundary = gpd.read_file(boundary_path).to_crs("EPSG:4326")
    boundary["geometry"] = boundary.geometry.simplify(0.0008, preserve_topology=True)
    return json.loads(boundary.to_json(drop_id=True))


def write_inline_html(boundary_path: Path, flows: gpd.GeoDataFrame, output_path: Path, html_top_k: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    boundary = compact_boundary(boundary_path)
    top = flows.head(html_top_k).to_crs("EPSG:4326")
    flow_rows = [
        {
            "rank": int(row.rank),
            "o": [round(float(row.origin_lon), 6), round(float(row.origin_lat), 6)],
            "d": [round(float(row.destination_lon), 6), round(float(row.destination_lat), 6)],
            "flow": int(round(float(row.flow))),
            "ol": str(row.origin_locations),
            "dl": str(row.destination_locations),
        }
        for row in top.itertuples(index=False)
    ]
    boundary_json = json.dumps(boundary, ensure_ascii=False, separators=(",", ":"))
    flows_json = json.dumps(flow_rows, ensure_ascii=False, separators=(",", ":"))
    fragment = f"""<div id="hk-od-flow-map" class="w-full">
  <div class="viz-row text-small text-muted" aria-live="polite">
    <span>Top {len(flow_rows):,} predicted WEDAN OD flows over the Hong Kong fixed-link boundary</span>
    <span>Max flow {int(top['flow'].max()):,}</span>
  </div>
  <svg class="hk-od-svg" role="img" aria-label="Hong Kong OD flow map" viewBox="0 0 920 620"></svg>
  <div class="hk-od-tooltip tooltip" role="status"></div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>
(function() {{
  const root = document.getElementById("hk-od-flow-map");
  const svg = d3.select(root).select("svg");
  const tip = root.querySelector(".hk-od-tooltip");
  const width = 920;
  const height = 620;
  const boundary = {boundary_json};
  const flows = {flows_json};
  const projection = d3.geoMercator().fitExtent([[18, 18], [width - 18, height - 18]], boundary);
  const path = d3.geoPath(projection);
  const flowExtent = d3.extent(flows, d => d.flow);
  const widthScale = d3.scaleSqrt().domain(flowExtent).range([0.35, 4.6]);
  const alphaScale = d3.scaleSqrt().domain(flowExtent).range([0.16, 0.72]);
  svg.selectAll("path.boundary")
    .data(boundary.features)
    .join("path")
    .attr("class", "boundary")
    .attr("d", path);
  svg.selectAll("line.flow")
    .data(flows)
    .join("line")
    .attr("class", "flow")
    .attr("x1", d => projection(d.o)[0])
    .attr("y1", d => projection(d.o)[1])
    .attr("x2", d => projection(d.d)[0])
    .attr("y2", d => projection(d.d)[1])
    .attr("stroke-width", d => widthScale(d.flow))
    .attr("stroke-opacity", d => alphaScale(d.flow))
    .on("mousemove", function(event, d) {{
      tip.textContent = `#${{d.rank}} ${{d.ol}} -> ${{d.dl}}: ${{d.flow.toLocaleString()}}`;
      tip.style.left = Math.min(event.offsetX + 14, width - 280) + "px";
      tip.style.top = Math.max(event.offsetY - 8, 8) + "px";
      tip.classList.add("is-visible");
      d3.select(this).classed("is-active", true);
    }})
    .on("mouseleave", function() {{
      tip.classList.remove("is-visible");
      d3.select(this).classed("is-active", false);
    }});
  svg.append("text")
    .attr("x", 22)
    .attr("y", height - 22)
    .attr("class", "map-note")
    .text("Line width encodes predicted OD flow.");
}})();
</script>
<style>
#hk-od-flow-map {{
  position: relative;
  color: var(--foreground);
}}
#hk-od-flow-map .hk-od-svg {{
  display: block;
  width: 100%;
  height: auto;
  min-height: 280px;
}}
#hk-od-flow-map .boundary {{
  fill: color-mix(in srgb, var(--muted) 35%, transparent);
  stroke: var(--border);
  stroke-width: 1;
}}
#hk-od-flow-map .flow {{
  stroke: var(--viz-series-1);
  stroke-linecap: round;
  fill: none;
}}
#hk-od-flow-map .flow.is-active {{
  stroke: var(--viz-series-2);
  stroke-opacity: 0.95;
}}
#hk-od-flow-map .map-note {{
  fill: var(--muted-foreground);
  font-size: 13px;
}}
#hk-od-flow-map .hk-od-tooltip {{
  position: absolute;
  pointer-events: none;
  opacity: 0;
  max-width: 280px;
}}
#hk-od-flow-map .hk-od-tooltip.is-visible {{
  opacity: 1;
}}
</style>
"""
    output_path.write_text(fragment, encoding="utf-8")


def main() -> None:
    args = parse_args()
    for path in [args.boundary, args.boundary_simplified, args.grid, args.od]:
        if not path.exists():
            raise FileNotFoundError(path)

    grid = gpd.read_file(args.grid).reset_index(drop=True)
    od = np.load(args.od)
    if od.shape[0] != len(grid):
        raise ValueError(f"OD/grid size mismatch: od={od.shape}, grid={len(grid)}")

    flows, grid_totals = build_flow_layers(grid, od, max(args.top_k, args.html_top_k))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = args.out_dir / "hong_kong_wedan_od_top_flows.csv"
    flows.drop(columns="geometry").to_csv(csv_path, index=False, encoding="utf-8-sig")

    geojson_path = args.out_dir / "hong_kong_wedan_od_top_flows.geojson"
    flows.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON")

    totals_path = args.out_dir / "hong_kong_wedan_od_grid_totals.csv"
    grid_totals.to_csv(totals_path, index=False, encoding="utf-8-sig")

    png_path = args.out_dir / "hong_kong_wedan_od_top_flows.png"
    save_static_map(args.boundary, flows.head(args.top_k), png_path)

    html_path = None
    if args.inline_html:
        html_path = args.inline_html
        write_inline_html(args.boundary_simplified, flows, html_path, args.html_top_k)

    summary = {
        "city": CITY_NAME,
        "boundary": str(args.boundary),
        "grid": str(args.grid),
        "od": str(args.od),
        "od_shape": list(od.shape),
        "od_total_flow": float(od.sum()),
        "od_nonzero": int(np.count_nonzero(od)),
        "top_k_static": int(args.top_k),
        "top_k_html": int(args.html_top_k),
        "top_flow_max": float(flows["flow"].max()),
        "top_flow_min_static": float(flows.head(args.top_k)["flow"].min()),
        "top_flow_sum_static": float(flows.head(args.top_k)["flow"].sum()),
        "outputs": {
            "png": str(png_path),
            "geojson": str(geojson_path),
            "csv": str(csv_path),
            "grid_totals_csv": str(totals_path),
            "inline_html": str(html_path) if html_path else None,
        },
        "note": "The map draws only the largest OD flows to keep the city-scale visualization legible.",
    }
    summary_path = args.out_dir / "hong_kong_wedan_od_flow_visualization_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {png_path}")
    print(f"Wrote: {geojson_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {summary_path}")
    if html_path:
        print(f"Wrote: {html_path}")
    print(f"OD total: {summary['od_total_flow']:.0f}; top {args.top_k} sum: {summary['top_flow_sum_static']:.0f}")


if __name__ == "__main__":
    main()
