from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib
import pandas as pd
from matplotlib import patheffects
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

matplotlib.use("Agg")


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TARGET_CRS = "EPSG:32650"
CJK_FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
CJK_FONT = FontProperties(fname=str(CJK_FONT_PATH)) if CJK_FONT_PATH.exists() else None

MTR_COLORS = {
    "AEL": "#00888A",
    "DRL": "#E777AE",
    "EAL": "#5EB6E4",
    "ISL": "#007DC5",
    "KTL": "#00AB4E",
    "SIL": "#B5BD00",
    "TCL": "#F7943E",
    "TKL": "#7D499D",
    "TML": "#9A3820",
    "TWL": "#ED1D24",
}

MTR_NAMES = {
    "AEL": "Airport Express",
    "DRL": "Disneyland Resort",
    "EAL": "East Rail",
    "ISL": "Island",
    "KTL": "Kwun Tong",
    "SIL": "South Island",
    "TCL": "Tung Chung",
    "TKL": "Tseung Kwan O",
    "TML": "Tuen Ma",
    "TWL": "Tsuen Wan",
}

LRT_COLORS = {
    "505": "#C43C39",
    "507": "#DB7B2B",
    "610": "#5B8C5A",
    "614": "#3F7CAC",
    "614P": "#855E9B",
    "615": "#2C7A7B",
    "615P": "#A34F77",
    "705": "#D8A21B",
    "706": "#6A8EAE",
    "751": "#8A6D3B",
    "761P": "#476A2E",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize current Hong Kong MTR and Light Rail routes and stops."
    )
    parser.add_argument(
        "--data-root", type=Path, default=PROJECT_ROOT / "data"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_context(ax: plt.Axes, boundary: gpd.GeoDataFrame) -> None:
    boundary.plot(
        ax=ax,
        facecolor="#F2F3F1",
        edgecolor="#8A918F",
        linewidth=0.7,
        zorder=0,
    )
    ax.set_facecolor("#DCE7EA")
    ax.set_aspect("equal")
    ax.set_axis_off()


def padded_extent(bounds: tuple[float, float, float, float], padding_m: float) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = bounds
    return minx - padding_m, maxx + padding_m, miny - padding_m, maxy + padding_m


def set_extent(ax: plt.Axes, extent: tuple[float, float, float, float]) -> None:
    xmin, xmax, ymin, ymax = extent
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)


def plot_lines(
    ax: plt.Axes,
    routes: gpd.GeoDataFrame,
    color_map: dict[str, str],
    linewidth: float,
) -> None:
    for route_id, group in routes.groupby("route_id", sort=True):
        color = color_map.get(str(route_id), "#555555")
        group.plot(
            ax=ax,
            color=color,
            linewidth=linewidth + 1.8,
            alpha=0.48,
            zorder=2,
        )
        group.plot(
            ax=ax,
            color=color,
            linewidth=linewidth,
            alpha=0.96,
            zorder=3,
        )


def plot_stops(
    ax: plt.Axes,
    stops: gpd.GeoDataFrame,
    *,
    base_size: float,
    interchange_size: float,
) -> None:
    ordinary = stops[~stops["is_interchange"]]
    interchange = stops[stops["is_interchange"]]
    ordinary.plot(
        ax=ax,
        color="#FFFFFF",
        edgecolor="#252B2D",
        linewidth=0.55,
        markersize=base_size,
        zorder=5,
    )
    if not interchange.empty:
        interchange.plot(
            ax=ax,
            color="#252B2D",
            edgecolor="#FFFFFF",
            linewidth=0.8,
            markersize=interchange_size,
            zorder=6,
        )


def label_selected_stops(
    ax: plt.Axes,
    stops: gpd.GeoDataFrame,
    *,
    label_terminals: bool = True,
    label_interchanges: bool = True,
    max_labels: int = 36,
) -> int:
    selected = stops[
        (stops["is_terminal"] if label_terminals else False)
        | (stops["is_interchange"] if label_interchanges else False)
    ].copy()
    selected = selected.sort_values(
        ["is_interchange", "line_count", "is_terminal"], ascending=False
    ).head(max_labels)
    offsets = [(5, 5), (5, -9), (-5, 5), (-5, -9), (7, 0), (-7, 0)]
    for index, (_, stop) in enumerate(selected.iterrows()):
        name = str(stop.get("stop_name_zh") or stop.get("stop_name_en") or "")
        if not name or name == "nan":
            continue
        dx, dy = offsets[index % len(offsets)]
        horizontal = "left" if dx >= 0 else "right"
        text = ax.annotate(
            name,
            xy=(stop.geometry.x, stop.geometry.y),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=6.2,
            fontproperties=CJK_FONT,
            color="#202426",
            ha=horizontal,
            va="center",
            zorder=8,
        )
        text.set_path_effects(
            [patheffects.withStroke(linewidth=2.2, foreground="#FFFFFF")]
        )
    return len(selected)


def route_legend(
    ax: plt.Axes,
    color_map: dict[str, str],
    labels: dict[str, str],
    *,
    title: str,
    columns: int,
) -> None:
    handles = [
        Line2D(
            [0],
            [0],
            color=color,
            linewidth=3.2,
            label=f"{code}  {labels.get(code, code)}",
        )
        for code, color in color_map.items()
    ]
    ax.legend(
        handles=handles,
        title=title,
        loc="lower left",
        ncol=columns,
        frameon=True,
        facecolor="#FFFFFF",
        edgecolor="#9AA1A3",
        framealpha=0.94,
        fontsize=7.2,
        title_fontsize=8.0,
    )


def save_figure(fig: plt.Figure, path: Path, dpi: int) -> None:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    if not path.exists() or path.stat().st_size < 50_000:
        raise RuntimeError(f"Visualization is missing or unexpectedly small: {path}")


def main() -> None:
    args = parse_args()
    transit_root = args.data_root / "transit/hongkong"
    output_dir = args.output_dir or (
        transit_root / "processed/mtr_lrt_route_stop_visualization_2026"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry_path = (
        transit_root
        / "processed/transit_route_link_mapmatching_2026_v2/matched_route_geometries_wgs84.geojson"
    )
    qa_path = (
        transit_root
        / "processed/transit_route_link_mapmatching_2026_v2/route_map_matching_qa.csv"
    )
    snaps_path = (
        transit_root
        / "processed/transit_route_link_mapmatching_2026_v2/stop_link_snaps.csv"
    )
    mtr_stops_path = transit_root / "MTR/mtr_lines_and_stations.csv"
    lrt_stops_path = transit_root / "MTR/light_rail_routes_and_stops.csv"
    boundary_path = (
        args.data_root
        / "boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
    )
    for path in [
        geometry_path,
        qa_path,
        snaps_path,
        mtr_stops_path,
        lrt_stops_path,
        boundary_path,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    routes = gpd.read_file(geometry_path)
    routes = routes[routes["mode"].isin(["mtr", "lrt"])].copy()
    qa = pd.read_csv(qa_path, dtype={"route_id": str, "route_seq": str})
    routes = routes.drop(columns=["acceptance_status"], errors="ignore").merge(
        qa[
            [
                "route_key",
                "route_id",
                "route_seq",
                "acceptance_status",
                "status",
                "confidence",
            ]
        ],
        on="route_key",
        how="left",
        validate="one_to_one",
    )
    routes = gpd.GeoDataFrame(routes, geometry="geometry", crs="EPSG:4326").to_crs(
        TARGET_CRS
    )

    snaps = pd.read_csv(
        snaps_path,
        low_memory=False,
        dtype={"route_id": str, "route_seq": str},
    )
    snaps = snaps[snaps["mode"].isin(["mtr", "lrt"])].copy()
    mtr_names = pd.read_csv(mtr_stops_path, dtype={"Line Code": str, "Direction": str})
    lrt_names = pd.read_csv(lrt_stops_path, dtype={"Line Code": str, "Direction": str})
    name_rows = []
    for frame, direction_col, stop_code_col in [
        (mtr_names, "Direction", "Station Code"),
        (lrt_names, "Direction", "Stop Code"),
    ]:
        normalized = frame.rename(
            columns={
                "Line Code": "route_id",
                direction_col: "route_seq",
                "Sequence": "stop_seq",
                "English Name": "official_name_en",
                "Chinese Name": "official_name_zh",
                stop_code_col: "official_stop_code",
            }
        )
        normalized["route_seq"] = normalized["route_seq"].astype(str)
        normalized["stop_seq"] = pd.to_numeric(
            normalized["stop_seq"], errors="coerce"
        )
        normalized = normalized.dropna(
            subset=["route_id", "route_seq", "stop_seq"]
        ).drop_duplicates(["route_id", "route_seq", "stop_seq"])
        name_rows.append(
            normalized[
                [
                    "route_id",
                    "route_seq",
                    "stop_seq",
                    "official_name_en",
                    "official_name_zh",
                    "official_stop_code",
                ]
            ]
        )
    names = pd.concat(name_rows, ignore_index=True)
    snaps["stop_seq"] = pd.to_numeric(snaps["stop_seq"], errors="coerce")
    snaps = snaps.merge(
        names,
        on=["route_id", "route_seq", "stop_seq"],
        how="left",
        validate="many_to_one",
    )
    # Map-matching route direction labels are not always identical to the MTR
    # table's direction convention. Preserve the snap table's correct Chinese
    # names and use sequence-derived official names only as a missing fallback.
    snaps["stop_name_en"] = snaps["stop_name_en"].fillna(
        snaps["official_name_en"]
    )
    snaps["stop_name_zh"] = snaps["stop_name_zh"].fillna(
        snaps["official_name_zh"]
    )
    group_extrema = snaps.groupby("route_key")["stop_seq"].transform(
        lambda values: values.eq(values.min()) | values.eq(values.max())
    )
    snaps["is_terminal_occurrence"] = group_extrema
    stop_line_counts = snaps.groupby(["mode", "stop_id"])["route_id"].nunique()
    stop_terminal = snaps.groupby(["mode", "stop_id"])[
        "is_terminal_occurrence"
    ].any()
    stop_names_en = snaps.groupby(["mode", "stop_id"])["stop_name_en"].first()
    stop_names_zh = snaps.groupby(["mode", "stop_id"])["stop_name_zh"].first()
    unique_stops = (
        snaps.sort_values(["mode", "stop_id", "snap_distance_m"])
        .drop_duplicates(["mode", "stop_id"])
        .copy()
    )
    index = pd.MultiIndex.from_frame(unique_stops[["mode", "stop_id"]])
    unique_stops["line_count"] = stop_line_counts.reindex(index).to_numpy()
    unique_stops["is_terminal"] = stop_terminal.reindex(index).to_numpy()
    unique_stops["stop_name_en"] = stop_names_en.reindex(index).to_numpy()
    unique_stops["stop_name_zh"] = stop_names_zh.reindex(index).to_numpy()
    unique_stops["is_interchange"] = unique_stops["line_count"].ge(2)
    stops = gpd.GeoDataFrame(
        unique_stops,
        geometry=gpd.points_from_xy(unique_stops["x"], unique_stops["y"]),
        crs=TARGET_CRS,
    )

    boundary = gpd.read_file(boundary_path).to_crs(TARGET_CRS)
    mtr_routes = routes[routes["mode"].eq("mtr")]
    lrt_routes = routes[routes["mode"].eq("lrt")]
    mtr_stops = stops[stops["mode"].eq("mtr")]
    lrt_stops = stops[stops["mode"].eq("lrt")]
    boundary_extent = padded_extent(tuple(boundary.total_bounds), 2_000)
    lrt_extent = padded_extent(tuple(lrt_routes.total_bounds), 1_400)

    combined_path = output_dir / "hong_kong_mtr_lrt_routes_stops.png"
    fig, ax = plt.subplots(figsize=(18, 14))
    add_context(ax, boundary)
    plot_lines(ax, mtr_routes, MTR_COLORS, linewidth=2.1)
    plot_lines(ax, lrt_routes, {key: "#6B4F2A" for key in LRT_COLORS}, linewidth=1.35)
    plot_stops(ax, mtr_stops, base_size=16, interchange_size=38)
    plot_stops(ax, lrt_stops, base_size=8, interchange_size=18)
    set_extent(ax, boundary_extent)
    ax.set_title(
        "Hong Kong MTR and Light Rail: Current Routes and Stops",
        fontsize=17,
        fontweight="normal",
        pad=14,
    )
    handles = [
        *[
            Line2D([0], [0], color=color, linewidth=3, label=f"{code}  {MTR_NAMES[code]}")
            for code, color in MTR_COLORS.items()
        ],
        Line2D([0], [0], color="#6B4F2A", linewidth=2.5, label="Light Rail network"),
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor="#FFFFFF",
            markeredgecolor="#252B2D",
            markersize=5,
            label="Station / stop",
        ),
    ]
    ax.legend(
        handles=handles,
        loc="lower left",
        ncol=2,
        frameon=True,
        facecolor="#FFFFFF",
        edgecolor="#9AA1A3",
        framealpha=0.94,
        fontsize=7.4,
    )
    ax.text(
        0.995,
        0.012,
        "Map-matched v2 geometry | 97 MTR stations | 68 Light Rail stops",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7.2,
        color="#454B4D",
        path_effects=[patheffects.withStroke(linewidth=2.5, foreground="#FFFFFF")],
    )
    save_figure(fig, combined_path, args.dpi)

    mtr_path = output_dir / "hong_kong_mtr_routes_stations.png"
    fig, ax = plt.subplots(figsize=(18, 14))
    add_context(ax, boundary)
    plot_lines(ax, mtr_routes, MTR_COLORS, linewidth=2.45)
    plot_stops(ax, mtr_stops, base_size=20, interchange_size=48)
    labeled_mtr = label_selected_stops(
        ax, mtr_stops, max_labels=38, label_terminals=True, label_interchanges=True
    )
    set_extent(ax, boundary_extent)
    ax.set_title("Hong Kong MTR Routes and Stations", fontsize=17, pad=14)
    route_legend(ax, MTR_COLORS, MTR_NAMES, title="MTR lines", columns=2)
    save_figure(fig, mtr_path, args.dpi)

    lrt_path = output_dir / "hong_kong_light_rail_routes_stops.png"
    fig, ax = plt.subplots(figsize=(16, 15))
    add_context(ax, boundary)
    plot_lines(ax, lrt_routes, LRT_COLORS, linewidth=2.25)
    plot_stops(ax, lrt_stops, base_size=24, interchange_size=46)
    labeled_lrt = label_selected_stops(
        ax, lrt_stops, max_labels=34, label_terminals=True, label_interchanges=True
    )
    set_extent(ax, lrt_extent)
    ax.set_title("Hong Kong Light Rail Routes and Stops", fontsize=17, pad=14)
    route_legend(
        ax,
        LRT_COLORS,
        {code: f"Route {code}" for code in LRT_COLORS},
        title="Light Rail routes",
        columns=3,
    )
    save_figure(fig, lrt_path, args.dpi)

    status_counts = (
        routes.groupby(["mode", "acceptance_status"])
        .size()
        .rename("count")
        .reset_index()
        .to_dict(orient="records")
    )
    summary: dict[str, Any] = {
        "inputs": {
            "route_geometry": str(geometry_path.resolve()),
            "route_qa": str(qa_path.resolve()),
            "stop_link_snaps": str(snaps_path.resolve()),
            "boundary": str(boundary_path.resolve()),
        },
        "crs": TARGET_CRS,
        "mtr": {
            "line_codes": sorted(mtr_routes["route_id"].astype(str).unique()),
            "route_directions": len(mtr_routes),
            "unique_stations": len(mtr_stops),
            "labeled_stations": labeled_mtr,
        },
        "light_rail": {
            "route_codes": sorted(lrt_routes["route_id"].astype(str).unique()),
            "route_directions": len(lrt_routes),
            "unique_stops": len(lrt_stops),
            "labeled_stops": labeled_lrt,
        },
        "acceptance_status_counts": status_counts,
        "outputs": {
            "combined": str(combined_path.resolve()),
            "mtr": str(mtr_path.resolve()),
            "light_rail": str(lrt_path.resolve()),
        },
    }
    (output_dir / "mtr_lrt_route_stop_visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files = [combined_path, mtr_path, lrt_path, output_dir / "mtr_lrt_route_stop_visualization_summary.json"]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{sha256_file(path)}  {path.name}" for path in files
        )
        + "\n",
        encoding="ascii",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
