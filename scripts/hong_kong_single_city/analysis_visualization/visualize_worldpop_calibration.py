#!/usr/bin/env python3
"""Visualize Hong Kong WorldPop calibration against 2021 Census targets."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW = ROOT / "data/gee/hongkong/worldpop_age_sex/worldpop_HKG_2020_pop_age_sex_hong_kong_fixed_link_boundary.tif"
DEFAULT_CAL = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex/census_calibrated"
    / "worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif"
)
DEFAULT_QA = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex/census_calibrated"
    / "worldpop_HKG_2021_census_lsug_calibration_qa.csv"
)
DEFAULT_DC = ROOT / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
DEFAULT_LSUG = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex/2021_Population_Census_Statistics_ LargeSubunitGroups"
    / "LSUG_21C_converted.shp"
)
DEFAULT_BOUNDARY = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary.geojson"
DEFAULT_OUT_DIR = ROOT / "data/gee/hongkong/worldpop_age_sex/census_calibrated"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-worldpop", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--calibrated-worldpop", type=Path, default=DEFAULT_CAL)
    parser.add_argument("--calibration-qa", type=Path, default=DEFAULT_QA)
    parser.add_argument("--districts", type=Path, default=DEFAULT_DC)
    parser.add_argument("--lsug", type=Path, default=DEFAULT_LSUG)
    parser.add_argument("--fixed-link-boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--html-fragment", type=Path, default=None)
    return parser.parse_args()


def raster_sum_by_zone(raster_path: Path, zones: gpd.GeoDataFrame, zone_field: str) -> dict[str, float]:
    with rasterio.open(raster_path) as src:
        data = src.read(1).astype("float64")
        zones_raster = zones.to_crs(src.crs)
        shapes = ((geom, idx + 1) for idx, geom in enumerate(zones_raster.geometry) if geom is not None and not geom.is_empty)
        zone_ids = rasterize(
            shapes=shapes,
            out_shape=(src.height, src.width),
            transform=src.transform,
            fill=0,
            dtype="int32",
            all_touched=False,
        )
    results: dict[str, float] = {}
    for idx, row in zones.iterrows():
        results[str(row[zone_field])] = float(data[zone_ids == idx + 1].sum(dtype="float64"))
    return results


def district_census_targets(
    districts: gpd.GeoDataFrame,
    lsug: gpd.GeoDataFrame,
    qa: pd.DataFrame,
    boundary: gpd.GeoDataFrame,
) -> dict[str, float]:
    target_by_lsbg = qa.set_index("lsbg")["target_total"].to_dict()
    fixed = boundary.to_crs(lsug.crs).geometry.union_all()
    lsug_work = lsug.copy()
    lsug_work["target_total"] = lsug_work["lsbg"].map(target_by_lsbg).fillna(0.0).astype(float)
    clipped_geom = lsug_work.geometry.intersection(fixed)
    points = gpd.GeoDataFrame(
        lsug_work[["lsbg", "target_total"]].copy(),
        geometry=clipped_geom.representative_point(),
        crs=lsug.crs,
    )
    points = points[points["target_total"] > 0]
    joined = gpd.sjoin(points, districts[["dc_eng", "geometry"]].to_crs(points.crs), how="left", predicate="within")
    return joined.groupby("dc_eng")["target_total"].sum().to_dict()


def build_data(args: argparse.Namespace) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    districts = gpd.read_file(args.districts)
    boundary = gpd.read_file(args.fixed_link_boundary)
    lsug = gpd.read_file(args.lsug)
    qa = pd.read_csv(args.calibration_qa)

    fixed = boundary.to_crs(districts.crs).geometry.union_all()
    district_clip = districts.copy()
    district_clip["geometry"] = district_clip.geometry.intersection(fixed)
    district_clip = district_clip[~district_clip.geometry.is_empty].copy()
    district_clip["area_km2"] = district_clip.geometry.area / 1_000_000.0

    raw_sums = raster_sum_by_zone(args.raw_worldpop, district_clip, "dc_eng")
    cal_sums = raster_sum_by_zone(args.calibrated_worldpop, district_clip, "dc_eng")
    target_sums = district_census_targets(districts, lsug, qa, boundary)

    records: list[dict[str, Any]] = []
    for _, row in district_clip.iterrows():
        name = str(row["dc_eng"])
        raw = raw_sums.get(name, 0.0)
        calibrated = cal_sums.get(name, 0.0)
        target = target_sums.get(name, 0.0)
        records.append(
            {
                "dc_eng": name,
                "dc_chi": str(row["dc_chi"]),
                "raw_worldpop": raw,
                "calibrated_worldpop": calibrated,
                "census_lsug_target": target,
                "raw_minus_target": raw - target,
                "calibrated_minus_target": calibrated - target,
                "raw_pct_error": (raw - target) / target * 100 if target else 0.0,
                "calibrated_pct_error": (calibrated - target) / target * 100 if target else 0.0,
                "area_km2": float(row["area_km2"]),
            }
        )

    stats = pd.DataFrame(records)
    merged = district_clip.drop(columns=["area_km2"]).merge(stats, on=["dc_eng", "dc_chi"], how="left")
    return merged, stats


def write_csv(stats: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(path, index=False, encoding="utf-8-sig")


def write_png(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plot_gdf = gdf.to_crs("EPSG:2326")
    values = ["raw_worldpop", "calibrated_worldpop", "census_lsug_target"]
    titles = ["Raw WorldPop 2020", "Census-calibrated WorldPop", "2021 Census LSUG target"]
    vmax = max(float(plot_gdf[col].max()) for col in values)

    fig, axes = plt.subplots(1, 3, figsize=(16, 6), dpi=180, constrained_layout=True)
    for ax, col, title in zip(axes, values, titles):
        plot_gdf.plot(column=col, ax=ax, cmap="viridis", vmin=0, vmax=vmax, linewidth=0.35, edgecolor="#333333")
        ax.set_title(title)
        ax.set_axis_off()
        ax.set_aspect("equal")
    sm = plt.cm.ScalarMappable(cmap="viridis", norm=plt.Normalize(vmin=0, vmax=vmax))
    sm._A = []
    cbar = fig.colorbar(sm, ax=axes, location="bottom", shrink=0.6, pad=0.02)
    cbar.set_label("Population by district within fixed-link model boundary")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def feature_collection(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    cols = [
        "dc_eng",
        "dc_chi",
        "raw_worldpop",
        "calibrated_worldpop",
        "census_lsug_target",
        "raw_pct_error",
        "calibrated_pct_error",
        "area_km2",
        "geometry",
    ]
    simple = gdf[cols].to_crs("EPSG:4326").copy()
    simple["geometry"] = simple.geometry.simplify(0.00025, preserve_topology=True)
    return json.loads(simple.to_json())


def write_html_fragment(gdf: gpd.GeoDataFrame, stats: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = feature_collection(gdf)
    totals = {
        "raw_worldpop": float(stats["raw_worldpop"].sum()),
        "calibrated_worldpop": float(stats["calibrated_worldpop"].sum()),
        "census_lsug_target": float(stats["census_lsug_target"].sum()),
    }
    max_value = float(stats[["raw_worldpop", "calibrated_worldpop", "census_lsug_target"]].max().max())
    payload = json.dumps({"features": fc, "totals": totals, "maxValue": max_value}, ensure_ascii=False)

    html = f"""<div id="hk-worldpop-calibration" class="viz-container">
  <style>
    #hk-worldpop-calibration {{
      color: var(--foreground);
    }}
    #hk-worldpop-calibration .hk-stats {{
      margin-bottom: 12px;
    }}
    #hk-worldpop-calibration .hk-map-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      align-items: start;
    }}
    #hk-worldpop-calibration .hk-map-title {{
      font-weight: 500;
      margin-bottom: 4px;
    }}
    #hk-worldpop-calibration svg {{
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
    }}
    #hk-worldpop-calibration .district {{
      stroke: var(--border);
      stroke-width: 0.7;
      vector-effect: non-scaling-stroke;
    }}
    #hk-worldpop-calibration .district:focus,
    #hk-worldpop-calibration .district:hover {{
      stroke: var(--foreground);
      stroke-width: 1.4;
      outline: none;
    }}
    #hk-worldpop-calibration .hk-label {{
      fill: var(--muted-foreground);
      text-anchor: middle;
      pointer-events: none;
    }}
    #hk-worldpop-calibration .hk-detail {{
      margin-top: 10px;
      min-height: 24px;
    }}
    #hk-worldpop-calibration .hk-legend {{
      display: flex;
      gap: 8px;
      align-items: center;
      margin-top: 8px;
      flex-wrap: wrap;
    }}
    #hk-worldpop-calibration .swatch {{
      width: 24px;
      height: 10px;
      background: var(--viz-series-1);
      border: 1px solid var(--border);
    }}
    @media (max-width: 680px) {{
      #hk-worldpop-calibration .hk-map-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
  <div class="viz-grid hk-stats" aria-label="Population totals">
    <div class="card viz-stat"><div class="text-muted">Raw WorldPop</div><div class="viz-stat-value" data-total="raw_worldpop"></div><div class="text-small text-muted">2020 clipped raster</div></div>
    <div class="card viz-stat"><div class="text-muted">Calibrated WorldPop</div><div class="viz-stat-value" data-total="calibrated_worldpop"></div><div class="text-small text-muted">2021 LSUG adjusted</div></div>
    <div class="card viz-stat"><div class="text-muted">Census target</div><div class="viz-stat-value" data-total="census_lsug_target"></div><div class="text-small text-muted">District aggregate</div></div>
  </div>
  <div class="hk-map-grid" role="group" aria-label="Population maps">
    <div><div class="hk-map-title">Raw WorldPop 2020</div><svg data-map="raw_worldpop" role="img" aria-label="Raw WorldPop 2020 population by district"></svg></div>
    <div><div class="hk-map-title">Calibrated WorldPop</div><svg data-map="calibrated_worldpop" role="img" aria-label="Calibrated WorldPop population by district"></svg></div>
    <div><div class="hk-map-title">2021 Census LSUG target</div><svg data-map="census_lsug_target" role="img" aria-label="2021 Census target population by district"></svg></div>
  </div>
  <div class="hk-legend text-small" aria-label="Legend">
    <span>Lower</span><span class="swatch" style="opacity:0.2"></span><span class="swatch" style="opacity:0.45"></span><span class="swatch" style="opacity:0.75"></span><span class="swatch" style="opacity:0.95"></span><span>Higher</span>
  </div>
  <div class="hk-detail text-small text-muted" aria-live="polite">District totals are people within the fixed-link model boundary.</div>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <script>
    (function() {{
      const root = document.getElementById('hk-worldpop-calibration');
      const payload = {payload};
      const data = payload.features;
      const totals = payload.totals;
      const maxValue = payload.maxValue;
      const format = new Intl.NumberFormat('en-US', {{ maximumFractionDigits: 0 }});
      const detail = root.querySelector('.hk-detail');
      root.querySelectorAll('[data-total]').forEach(el => {{
        el.textContent = format.format(totals[el.dataset.total] || 0);
      }});
      const width = 260;
      const height = 210;
      const projection = d3.geoMercator().fitSize([width, height], data);
      const path = d3.geoPath(projection);
      function opacity(value) {{
        return Math.max(0.16, Math.min(0.95, 0.16 + 0.79 * Math.sqrt((value || 0) / maxValue)));
      }}
      function render(svgEl, field) {{
        const svg = d3.select(svgEl).attr('viewBox', `0 0 ${{width}} ${{height}}`);
        svg.selectAll('path')
          .data(data.features)
          .join('path')
          .attr('class', 'district')
          .attr('d', path)
          .attr('fill', 'var(--viz-series-1)')
          .attr('fill-opacity', d => opacity(d.properties[field]))
          .attr('aria-label', d => `${{d.properties.dc_eng}}: ${{format.format(d.properties[field] || 0)}}`)
          .on('mouseenter focus', function(event, d) {{
            const p = d.properties;
            detail.textContent = `${{p.dc_eng}}: raw ${{format.format(p.raw_worldpop)}}, calibrated ${{format.format(p.calibrated_worldpop)}}, Census target ${{format.format(p.census_lsug_target)}}; calibrated error ${{(p.calibrated_pct_error || 0).toFixed(2)}}%.`;
          }})
          .on('mouseleave blur', function() {{
            detail.textContent = 'District totals are people within the fixed-link model boundary.';
          }});
        svg.selectAll('text')
          .data(data.features.filter(d => (d.properties.area_km2 || 0) > 9))
          .join('text')
          .attr('class', 'hk-label text-small')
          .attr('x', d => path.centroid(d)[0])
          .attr('y', d => path.centroid(d)[1])
          .text(d => d.properties.dc_eng.split(' ')[0])
          .style('font-size', '9px');
      }}
      root.querySelectorAll('svg[data-map]').forEach(svg => render(svg, svg.dataset.map));
    }})();
  </script>
</div>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    gdf, stats = build_data(args)
    csv_path = args.out_dir / "hong_kong_worldpop_calibration_district_comparison.csv"
    png_path = args.out_dir / "hong_kong_worldpop_calibration_district_comparison.png"
    write_csv(stats, csv_path)
    write_png(gdf, png_path)
    if args.html_fragment:
        write_html_fragment(gdf, stats, args.html_fragment)
    print(json.dumps({
        "districts": int(len(stats)),
        "raw_total": float(stats["raw_worldpop"].sum()),
        "calibrated_total": float(stats["calibrated_worldpop"].sum()),
        "census_target_total": float(stats["census_lsug_target"].sum()),
        "csv": str(csv_path),
        "png": str(png_path),
        "html_fragment": str(args.html_fragment) if args.html_fragment else None,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
