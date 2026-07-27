from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = PROJECT_ROOT / "data/transit/hongkong/processed"
DEFAULT_INPUT = PROCESSED_ROOT / "transit_route_link_mapmatching_2026_v2"
DEFAULT_BASELINE = PROCESSED_ROOT / "transit_route_link_mapmatching_2026"
DEFAULT_BOUNDARY = (
    PROJECT_ROOT
    / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
)
DEFAULT_DISTRICTS = (
    PROJECT_ROOT
    / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP"
    / "DC_21C_converted.shp"
)
MODEL_CRS = "EPSG:32650"
HIGH_RATIO_THRESHOLD = 1.5
STOP_COVERAGE_THRESHOLD_M = 250.0
COLORS = {
    "high_ratio": "#d95f02",
    "coverage": "#1b78a6",
    "both": "#a51c4b",
    "other_review": "#6b6f76",
    "candidate_dp": "#16817a",
    "trajectory_evidence": "#6a51a3",
    "cyclic_or_ordered": "#c17c0e",
    "boundary": "#4f5962",
    "district": "#aab2b8",
    "land": "#f1f3f4",
    "flagged_stop": "#a51c4b",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize v1/v2 Hong Kong transit map-matching repairs and reviews."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--districts", type=Path, default=DEFAULT_DISTRICTS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--atlas-routes-per-page", type=int, default=20)
    return parser.parse_args()


def as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def read_qa(path: Path, *, v2: bool) -> pd.DataFrame:
    qa = pd.read_csv(path, low_memory=False)
    numeric_columns = [
        "matched_to_trajectory_length_ratio",
        "coverage_warning_stop_count",
        "stop_coverage_max_m",
        "source_to_matched_p95_m",
        "matched_to_source_p95_m",
        "repeated_link_length_share",
        "maximum_connector_length_m",
    ]
    for column in numeric_columns:
        if column not in qa:
            qa[column] = np.nan
        qa[column] = pd.to_numeric(qa[column], errors="coerce")
    qa["high_ratio"] = (
        qa["mode"].isin(["bus", "gmb"])
        & qa["matched_to_trajectory_length_ratio"].gt(HIGH_RATIO_THRESHOLD)
    )
    if v2:
        qa["coverage_warning"] = qa["coverage_warning_stop_count"].fillna(0).gt(0)
        qa["manual_review"] = qa["acceptance_status"].ne("accepted")
        qa["stop_order_warning"] = ~as_bool(qa["stop_assignment_ordered"])
    else:
        qa["coverage_warning"] = qa["status"].eq("partial_external")
        qa["manual_review"] = qa["high_ratio"] | qa["coverage_warning"]
        qa["stop_order_warning"] = False
    qa["review_class"] = np.select(
        [
            qa["high_ratio"] & qa["coverage_warning"],
            qa["high_ratio"],
            qa["coverage_warning"],
        ],
        ["both", "high_ratio", "coverage"],
        default="other_review",
    )
    qa["display_name"] = (
        qa["mode"].str.upper()
        + " "
        + qa["route_name"].fillna(qa["route_id"].astype(str)).astype(str)
        + " / dir "
        + qa["route_seq"].astype(str)
        + " ["
        + qa["route_id"].astype(str)
        + "]"
    )
    return qa


def load_inputs(args: argparse.Namespace) -> tuple[
    gpd.GeoDataFrame,
    pd.DataFrame,
    pd.DataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    pd.DataFrame,
    gpd.GeoDataFrame,
]:
    qa_path = args.input_dir / "route_map_matching_qa.csv"
    route_path = args.input_dir / "matched_route_geometries_wgs84.geojson"
    stop_path = args.input_dir / "stop_link_snaps.csv"
    baseline_path = args.baseline_dir / "route_map_matching_qa.csv"
    for path in (
        qa_path,
        route_path,
        stop_path,
        baseline_path,
        args.boundary,
        args.districts,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    qa_all = read_qa(qa_path, v2=True)
    qa_review = qa_all.loc[qa_all["manual_review"]].copy()
    baseline = read_qa(baseline_path, v2=False)

    routes_all = (
        gpd.read_file(route_path)
        .to_crs(MODEL_CRS)
        .drop_duplicates("route_key")[["route_key", "geometry"]]
    )
    merge_columns = [
        "route_key",
        "display_name",
        "review_class",
        "high_ratio",
        "coverage_warning",
        "manual_review",
        "stop_order_warning",
        "matched_to_trajectory_length_ratio",
        "coverage_warning_stop_count",
        "stop_coverage_max_m",
        "source_to_matched_p95_m",
        "matched_to_source_p95_m",
        "repeated_link_length_share",
        "maximum_connector_length_m",
        "trajectory_source",
        "status",
        "repair_method",
        "acceptance_status",
    ]
    routes_review = routes_all.merge(
        qa_review[merge_columns], on="route_key", how="inner", validate="one_to_one"
    )
    routes_review = gpd.GeoDataFrame(routes_review, geometry="geometry", crs=MODEL_CRS)

    accepted_repairs = qa_all.loc[
        qa_all["acceptance_status"].eq("accepted")
        & qa_all["repair_method"].fillna("none").ne("none")
    ].copy()
    accepted_repairs["repair_class"] = np.select(
        [
            accepted_repairs["repair_method"].str.contains("trajectory_evidence", na=False),
            accepted_repairs["repair_method"].str.contains(
                "cyclic|ordered_stop", case=False, regex=True, na=False
            ),
        ],
        ["trajectory_evidence", "cyclic_or_ordered"],
        default="candidate_dp",
    )
    routes_repaired = routes_all.merge(
        accepted_repairs[["route_key", "repair_class", "repair_method"]],
        on="route_key",
        how="inner",
        validate="one_to_one",
    )
    routes_repaired = gpd.GeoDataFrame(routes_repaired, geometry="geometry", crs=MODEL_CRS)

    stops = pd.read_csv(stop_path, low_memory=False)
    stops["coverage_distance_m"] = pd.to_numeric(stops["coverage_distance_m"], errors="coerce")
    stops = stops.loc[
        stops["coverage_distance_m"].gt(STOP_COVERAGE_THRESHOLD_M)
        & stops["route_key"].isin(qa_review["route_key"])
    ].copy()
    flagged_stops = gpd.GeoDataFrame(
        stops,
        geometry=gpd.points_from_xy(stops["x"], stops["y"]),
        crs=MODEL_CRS,
    )
    boundary = gpd.read_file(args.boundary).to_crs(MODEL_CRS)
    districts = gpd.read_file(args.districts).to_crs(MODEL_CRS)
    boundary.geometry = boundary.geometry.simplify(30.0, preserve_topology=True)
    districts.geometry = districts.geometry.simplify(20.0, preserve_topology=True)
    return (
        routes_review,
        qa_review,
        qa_all,
        flagged_stops,
        boundary,
        districts,
        baseline,
        routes_repaired,
    )


def configure_map(ax: plt.Axes, boundary: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> None:
    boundary.plot(ax=ax, color=COLORS["land"], edgecolor=COLORS["boundary"], linewidth=0.65)
    districts.boundary.plot(ax=ax, color=COLORS["district"], linewidth=0.35, alpha=0.8)
    minx, miny, maxx, maxy = boundary.total_bounds
    padx = (maxx - minx) * 0.025
    pady = (maxy - miny) * 0.025
    ax.set_xlim(minx - padx, maxx + padx)
    ax.set_ylim(miny - pady, maxy + pady)
    ax.set_aspect("equal")
    ax.set_axis_off()


def line_widths(values: pd.Series, low: float = 0.55, high: float = 2.4) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0).to_numpy(dtype=float)
    transformed = np.sqrt(np.maximum(numeric, 0))
    if len(transformed) == 0 or transformed.max() <= transformed.min():
        return np.full(len(transformed), (low + high) / 2)
    return low + (high - low) * (transformed - transformed.min()) / (
        transformed.max() - transformed.min()
    )


def plot_overview(
    routes: gpd.GeoDataFrame,
    stops: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(21, 7.7), dpi=220)
    panels = [
        (routes.loc[routes["high_ratio"]], "Road reference-length ratio > 1.5", "high_ratio"),
        (routes.loc[routes["coverage_warning"]], "Official stop coverage distance > 250 m", "coverage"),
        (routes, "All routes retained for manual review", "review"),
    ]
    for ax, (selected, title, panel) in zip(axes, panels, strict=True):
        configure_map(ax, boundary, districts)
        if panel == "review":
            for category in ("other_review", "coverage", "high_ratio", "both"):
                subset = selected.loc[selected["review_class"].eq(category)]
                if not subset.empty:
                    subset.plot(ax=ax, color=COLORS[category], linewidth=0.9, alpha=0.82, zorder=3)
        elif not selected.empty:
            width_column = (
                "matched_to_trajectory_length_ratio"
                if panel == "high_ratio"
                else "coverage_warning_stop_count"
            )
            selected.plot(
                ax=ax,
                color=COLORS[panel],
                linewidth=line_widths(selected[width_column]),
                alpha=0.84,
                zorder=3,
            )
        if panel in {"coverage", "review"} and not stops.empty:
            selected_stops = stops.loc[stops["route_key"].isin(set(selected["route_key"]))]
            if not selected_stops.empty:
                selected_stops.plot(
                    ax=ax,
                    color=COLORS["flagged_stop"],
                    marker="x",
                    markersize=9,
                    linewidth=0.8,
                    alpha=0.75,
                    zorder=4,
                )
        ax.set_title(f"{title}\n{len(selected):,} route directions", fontsize=11)
    legend = [
        Line2D([0], [0], color=COLORS["high_ratio"], linewidth=2.4, label="High length ratio"),
        Line2D([0], [0], color=COLORS["coverage"], linewidth=2.4, label="Stop coverage warning"),
        Line2D([0], [0], color=COLORS["both"], linewidth=2.8, label="Both warnings"),
        Line2D([0], [0], color=COLORS["other_review"], linewidth=2.4, label="Other strict-QA review"),
        Line2D([0], [0], color=COLORS["flagged_stop"], marker="x", linestyle="None", label="Stop > 250 m"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=5, frameon=False, fontsize=9)
    fig.suptitle("Hong Kong transit map-matching v2: remaining review routes", fontsize=15, y=0.98)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_before_after(
    baseline: pd.DataFrame,
    qa: pd.DataFrame,
    output_path: Path,
) -> None:
    comparison = pd.DataFrame(
        {
            "metric": ["Road ratio > 1.5", "partial_external status"],
            "v1": [int(baseline["high_ratio"].sum()), int(baseline["coverage_warning"].sum())],
            "v2": [int(qa["high_ratio"].sum()), int(qa["status"].eq("partial_external").sum())],
        }
    )
    x = np.arange(len(comparison))
    width = 0.34
    fig, ax = plt.subplots(figsize=(9.6, 5.8), dpi=220)
    old_bars = ax.bar(x - width / 2, comparison["v1"], width, label="v1", color="#aeb5bb")
    new_bars = ax.bar(x + width / 2, comparison["v2"], width, label="v2", color="#16817a")
    ax.bar_label(old_bars, padding=4, fontsize=10)
    ax.bar_label(new_bars, padding=4, fontsize=10)
    ax.set_xticks(x, comparison["metric"])
    ax.set_ylabel("Route directions")
    ax.set_title("Map-matching anomaly counts before and after repair", fontsize=13)
    ax.grid(axis="y", linewidth=0.5, color="#d7dce0")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.legend(frameon=False)
    old_partial_keys = set(baseline.loc[baseline["coverage_warning"], "route_key"])
    old_partial_new = qa.loc[qa["route_key"].isin(old_partial_keys)]
    accepted = int(old_partial_new["acceptance_status"].eq("accepted").sum())
    no_coverage = int((~old_partial_new["coverage_warning"]).sum())
    ax.text(
        0.02,
        0.95,
        f"Old partial_external cohort: {no_coverage}/{len(old_partial_new)} now have no 250 m coverage warning; "
        f"{accepted}/{len(old_partial_new)} accepted.",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
        color="#384047",
    )
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_rankings(qa: pd.DataFrame, output_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 10), dpi=220)
    high = qa.loc[qa["high_ratio"]].nlargest(30, "matched_to_trajectory_length_ratio").sort_values(
        "matched_to_trajectory_length_ratio"
    )
    coverage = qa.loc[qa["coverage_warning"]].nlargest(
        30, "stop_coverage_max_m"
    ).sort_values("stop_coverage_max_m")
    frames = [
        (high, "matched_to_trajectory_length_ratio", "Remaining road length-ratio warnings", "Reference-length ratio"),
        (coverage, "stop_coverage_max_m", "Top 30 official-stop coverage distances", "Maximum coverage distance (m)"),
    ]
    for ax, (frame, value_col, title, xlabel) in zip(axes, frames, strict=True):
        colors = frame["review_class"].map(COLORS)
        bars = ax.barh(frame["display_name"], frame[value_col], color=colors, alpha=0.9)
        labels = [f"{value:.2f}" if value_col.endswith("ratio") else f"{value:,.0f}" for value in frame[value_col]]
        ax.bar_label(bars, labels=labels, padding=3, fontsize=7)
        ax.set_title(title, fontsize=12)
        ax.set_xlabel(xlabel)
        ax.grid(axis="x", color="#d7dce0", linewidth=0.5)
        ax.tick_params(axis="y", labelsize=7)
        ax.spines[["top", "right", "left"]].set_visible(False)
    fig.suptitle("Hong Kong transit map-matching v2 review priorities", fontsize=15, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_accepted_repairs(
    routes: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(21, 7.7), dpi=220)
    panels = [
        ("candidate_dp", "Candidate-sequence / legal-path repairs"),
        ("trajectory_evidence", "CSDI + official-stop evidence links"),
        ("cyclic_or_ordered", "Cyclic reordering / ordered-stop repairs"),
    ]
    for ax, (category, title) in zip(axes, panels, strict=True):
        configure_map(ax, boundary, districts)
        selected = routes.loc[routes["repair_class"].eq(category)]
        if not selected.empty:
            selected.plot(ax=ax, color=COLORS[category], linewidth=0.8, alpha=0.78, zorder=3)
        ax.set_title(f"{title}\n{len(selected):,} accepted route directions", fontsize=11)
    legend = [
        Line2D([0], [0], color=COLORS[key], linewidth=2.5, label=label)
        for key, label in (
            ("candidate_dp", "Candidate sequence / legal path"),
            ("trajectory_evidence", "Trajectory evidence links"),
            ("cyclic_or_ordered", "Cyclic / ordered stop repair"),
        )
    ]
    fig.legend(handles=legend, loc="lower center", ncol=3, frameon=False)
    fig.suptitle("Accepted v2 route repairs", fontsize=15, y=0.98)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def route_extent(
    geometry: object,
    route_stops: gpd.GeoDataFrame,
    minimum_span_m: float = 2500.0,
) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = geometry.bounds
    if not route_stops.empty:
        sx1, sy1, sx2, sy2 = route_stops.total_bounds
        minx, miny, maxx, maxy = min(minx, sx1), min(miny, sy1), max(maxx, sx2), max(maxy, sy2)
    span = max(maxx - minx, maxy - miny, minimum_span_m)
    padding = span * 0.12
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return cx - span / 2 - padding, cy - span / 2 - padding, cx + span / 2 + padding, cy + span / 2 + padding


def plot_atlas(
    routes: gpd.GeoDataFrame,
    stops: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    output_dir: Path,
    per_page: int,
) -> list[Path]:
    ordered = routes.assign(
        high_priority=routes["high_ratio"].astype(int),
        coverage_priority=routes["coverage_warning"].astype(int),
    ).sort_values(
        ["high_priority", "coverage_priority", "matched_to_trajectory_length_ratio", "route_key"],
        ascending=[False, False, False, True],
    )
    columns = 4
    rows = math.ceil(per_page / columns)
    pages: list[Path] = []
    for start in range(0, len(ordered), per_page):
        page = ordered.iloc[start : start + per_page]
        fig, axes = plt.subplots(rows, columns, figsize=(16, rows * 3.35), dpi=200)
        axes_array = np.asarray(axes).reshape(-1)
        for ax, (_, route) in zip(axes_array, page.iterrows(), strict=False):
            route_stops = stops.loc[stops["route_key"].eq(route["route_key"])]
            minx, miny, maxx, maxy = route_extent(route.geometry, route_stops)
            local_boundary = boundary.cx[minx:maxx, miny:maxy]
            local_districts = districts.cx[minx:maxx, miny:maxy]
            if not local_boundary.empty:
                local_boundary.plot(ax=ax, color=COLORS["land"], edgecolor=COLORS["boundary"], linewidth=0.3)
            if not local_districts.empty:
                local_districts.boundary.plot(ax=ax, color=COLORS["district"], linewidth=0.25)
            color = COLORS[route["review_class"]]
            gpd.GeoSeries([route.geometry], crs=MODEL_CRS).plot(ax=ax, color=color, linewidth=2.0, zorder=3)
            if not route_stops.empty:
                route_stops.plot(ax=ax, color=COLORS["flagged_stop"], marker="x", markersize=17, linewidth=0.9, zorder=4)
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
            ax.set_aspect("equal")
            ax.set_axis_off()
            ratio = route["matched_to_trajectory_length_ratio"]
            ratio_label = "NA" if pd.isna(ratio) else f"{ratio:.2f}"
            coverage = int(route["coverage_warning_stop_count"] or 0)
            ax.set_title(
                f"{route['display_name']}\nratio {ratio_label} | coverage stops {coverage} | {route['status']}",
                fontsize=7.5,
            )
        for ax in axes_array[len(page) :]:
            ax.set_axis_off()
        page_number = start // per_page + 1
        path = output_dir / f"manual_review_route_atlas_{page_number:02d}.png"
        fig.suptitle(
            f"v2 manual-review route atlas | directions {start + 1}-{start + len(page)} of {len(ordered)}",
            fontsize=14,
            y=0.995,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.98))
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        pages.append(path)
    return pages


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or args.input_dir / "qa_visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    routes, qa, qa_all, stops, boundary, districts, baseline, repaired = load_inputs(args)
    if len(routes) != len(qa):
        raise ValueError(f"Expected one geometry per review direction: routes={len(routes)}, qa={len(qa)}")

    overview = output_dir / "remaining_manual_review_overview.png"
    rankings = output_dir / "remaining_manual_review_rankings.png"
    before_after = output_dir / "map_matching_v1_v2_comparison.png"
    accepted_repairs = output_dir / "accepted_repairs_overview.png"
    plot_overview(routes, stops, boundary, districts, overview)
    plot_rankings(qa, rankings)
    plot_before_after(baseline, qa_all, before_after)
    plot_accepted_repairs(repaired, boundary, districts, accepted_repairs)
    atlas_pages = plot_atlas(routes, stops, boundary, districts, output_dir, max(args.atlas_routes_per_page, 1))

    inventory_columns = [
        "route_key",
        "display_name",
        "mode",
        "route_id",
        "route_seq",
        "route_name",
        "trajectory_source",
        "status",
        "acceptance_status",
        "review_class",
        "repair_method",
        "matched_to_trajectory_length_ratio",
        "coverage_warning_stop_count",
        "stop_coverage_max_m",
        "source_to_matched_p95_m",
        "matched_to_source_p95_m",
        "repeated_link_length_share",
        "maximum_connector_length_m",
    ]
    qa.sort_values(
        ["high_ratio", "coverage_warning", "matched_to_trajectory_length_ratio"],
        ascending=[False, False, False],
    )[inventory_columns].to_csv(output_dir / "manual_review_route_inventory.csv", index=False)

    old_partial_keys = set(baseline.loc[baseline["coverage_warning"], "route_key"])
    old_partial_new = qa_all.loc[qa_all["route_key"].isin(old_partial_keys)]
    summary = {
        "manual_review_route_directions": int(len(qa)),
        "high_ratio_directions": int(qa["high_ratio"].sum()),
        "coverage_warning_directions": int(qa["coverage_warning"].sum()),
        "stop_order_warning_directions": int(qa["stop_order_warning"].sum()),
        "flagged_stop_occurrences": int(len(stops)),
        "accepted_repair_directions_visualized": int(len(repaired)),
        "v1_high_ratio_directions": int(baseline["high_ratio"].sum()),
        "v1_partial_external_directions": int(baseline["coverage_warning"].sum()),
        "v2_partial_external_directions": int(qa_all["status"].eq("partial_external").sum()),
        "old_partial_external_now_without_coverage_warning": int((~old_partial_new["coverage_warning"]).sum()),
        "old_partial_external_now_accepted": int(old_partial_new["acceptance_status"].eq("accepted").sum()),
        "length_ratio_threshold": HIGH_RATIO_THRESHOLD,
        "stop_coverage_threshold_m": STOP_COVERAGE_THRESHOLD_M,
        "overview_png": str(overview),
        "rankings_png": str(rankings),
        "before_after_png": str(before_after),
        "accepted_repairs_png": str(accepted_repairs),
        "atlas_pages": [str(path) for path in atlas_pages],
    }
    (output_dir / "manual_review_visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
