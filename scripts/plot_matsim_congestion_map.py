from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import zstandard as zstd
from shapely import wkt


def read_zst_text(path: Path) -> io.TextIOWrapper:
    fh = path.open("rb")
    reader = zstd.ZstdDecompressor().stream_reader(fh)
    # Attach the binary file handle to the wrapper so it remains alive.
    txt = io.TextIOWrapper(reader, encoding="utf-8", newline="")
    txt._matsim_file_handle = fh  # type: ignore[attr-defined]
    return txt


def load_links(output_dir: Path) -> gpd.GeoDataFrame:
    with read_zst_text(output_dir / "output_links.csv.zst") as f:
        links = pd.read_csv(f, sep=";")
    links["geometry"] = links["geometry"].map(wkt.loads)
    return gpd.GeoDataFrame(links, geometry="geometry", crs="EPSG:32650")


def build_congestion_map(output_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    links = load_links(output_dir)
    traffic = pd.read_csv(output_dir / "analysis" / "traffic" / "traffic_stats_by_link_daily.csv")
    gdf = links.merge(traffic, left_on="link", right_on="link_id", how="inner")

    # Keep links that were actually used. Very low-volume links can dominate visually
    # without telling much about experienced congestion.
    used = gdf[gdf["simulated_traffic_volume"] > 0].copy()
    severe = used[(used["congestion_index"] < 0.5) & (used["simulated_traffic_volume"] >= 50)].copy()
    very_severe = used[(used["congestion_index"] < 0.3) & (used["simulated_traffic_volume"] >= 50)].copy()

    def linewidth(series: pd.Series) -> pd.Series:
        q95 = max(float(series.quantile(0.95)), 1.0)
        return (0.15 + 2.8 * (series.clip(upper=q95) / q95)).clip(lower=0.15, upper=3.0)

    used["plot_width"] = linewidth(used["simulated_traffic_volume"])
    severe["plot_width"] = linewidth(severe["simulated_traffic_volume"])

    fig, axes = plt.subplots(1, 2, figsize=(18, 10), dpi=220)
    fig.patch.set_facecolor("white")

    base = used[used["simulated_traffic_volume"] > 0]
    base.plot(ax=axes[0], color="#d9d9d9", linewidth=0.15, alpha=0.35)
    used.plot(
        ax=axes[0],
        column="congestion_index",
        cmap="RdYlGn",
        vmin=0.2,
        vmax=1.0,
        linewidth=used["plot_width"],
        alpha=0.9,
        legend=True,
        legend_kwds={"label": "Daily link congestion index", "shrink": 0.65},
    )
    axes[0].set_title("All used links: color = congestion index, width = traffic volume")
    axes[0].set_axis_off()
    axes[0].set_aspect("equal")

    base.plot(ax=axes[1], color="#eeeeee", linewidth=0.12, alpha=0.45)
    if not severe.empty:
        severe.plot(
            ax=axes[1],
            column="congestion_index",
            cmap="Reds_r",
            vmin=0.2,
            vmax=0.5,
            linewidth=severe["plot_width"],
            alpha=0.95,
            legend=True,
            legend_kwds={"label": "Severe links only (<0.5)", "shrink": 0.65},
        )
    axes[1].set_title("Severe bottlenecks: congestion index < 0.5 and volume >= 50")
    axes[1].set_axis_off()
    axes[1].set_aspect("equal")

    for ax in axes:
        ax.margins(0.02)

    png = out_dir / "daily_link_congestion_map.png"
    fig.tight_layout()
    fig.savefig(png, bbox_inches="tight")
    plt.close(fig)

    severe_geojson = out_dir / "severe_congested_links_daily.geojson"
    severe.drop(columns=["plot_width"], errors="ignore").to_file(severe_geojson, driver="GeoJSON")

    summary = {
        "output_dir": str(output_dir),
        "used_links": int(len(used)),
        "all_links_with_traffic_stats": int(len(gdf)),
        "mean_congestion_index_used_links": float(used["congestion_index"].mean()),
        "median_congestion_index_used_links": float(used["congestion_index"].median()),
        "links_ci_lt_0_75": int((used["congestion_index"] < 0.75).sum()),
        "links_ci_lt_0_50": int((used["congestion_index"] < 0.5).sum()),
        "links_ci_lt_0_30": int((used["congestion_index"] < 0.3).sum()),
        "severe_links_volume_ge_50": int(len(severe)),
        "very_severe_links_volume_ge_50": int(len(very_severe)),
        "png": str(png),
        "severe_geojson": str(severe_geojson),
    }
    (out_dir / "daily_link_congestion_map_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    out_dir = Path(args.out_dir) if args.out_dir else output_dir / "analysis" / "traffic"
    summary = build_congestion_map(output_dir, out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
