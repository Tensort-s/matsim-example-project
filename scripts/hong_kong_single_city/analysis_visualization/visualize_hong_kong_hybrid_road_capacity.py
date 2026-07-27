#!/usr/bin/env python3
"""Visualize the Hong Kong hybrid MATSim road-capacity candidate."""

from __future__ import annotations

import argparse
import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
MAP_CRS = "EPSG:32650"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--capacity-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def read_road_segments(
    network_path: Path,
    road_link_ids: set[str],
) -> tuple[np.ndarray, list[str]]:
    nodes: dict[str, tuple[float, float]] = {}
    segments: list[list[tuple[float, float]]] = []
    link_ids: list[str] = []
    with gzip.open(network_path, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag == "node":
                nodes[element.attrib["id"]] = (
                    float(element.attrib["x"]),
                    float(element.attrib["y"]),
                )
            elif element.tag == "link":
                link_id = element.attrib["id"]
                if link_id in road_link_ids:
                    from_node = nodes.get(element.attrib["from"])
                    to_node = nodes.get(element.attrib["to"])
                    if from_node is None or to_node is None:
                        raise RuntimeError(
                            f"Missing endpoint for MATSim link {link_id}"
                        )
                    segments.append([from_node, to_node])
                    link_ids.append(link_id)
            element.clear()
    missing = road_link_ids - set(link_ids)
    if missing:
        raise RuntimeError(
            f"{len(missing)} capacity-table links are absent from the network."
        )
    return np.asarray(segments, dtype=np.float64), link_ids


def add_capacity_collection(
    axis: plt.Axes,
    segments: np.ndarray,
    values: np.ndarray,
    boundaries: list[float],
    colors: list[str],
    linewidths: np.ndarray,
    label: str,
) -> None:
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(boundaries, cmap.N, clip=True)
    collection = LineCollection(
        segments,
        cmap=cmap,
        norm=norm,
        linewidths=linewidths,
        alpha=0.9,
        capstyle="round",
        zorder=2,
    )
    collection.set_array(values)
    axis.add_collection(collection)
    colorbar = axis.figure.colorbar(
        collection,
        ax=axis,
        boundaries=boundaries,
        ticks=boundaries,
        fraction=0.028,
        pad=0.012,
    )
    colorbar.set_label(label)
    colorbar.ax.tick_params(labelsize=8)


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    capacity_dir = (
        args.capacity_dir.resolve()
        if args.capacity_dir
        else project_root
        / "data/transit/hongkong/processed/"
        "road_capacity_hybrid_tpdm_flow_2026_v1"
    )
    output = (
        args.output.resolve()
        if args.output
        else capacity_dir / "hong_kong_hybrid_road_capacity_map.png"
    )
    links_path = capacity_dir / "hybrid_capacity_matsim_links.csv"
    network_path = capacity_dir / "network_hybrid_capacity.xml.gz"
    boundary_path = (
        project_root
        / "data/boundary/hongkong/processed/"
        "hong_kong_fixed_link_boundary_wgs84.geojson"
    )
    missing = [
        str(path)
        for path in [links_path, network_path, boundary_path]
        if not path.exists()
    ]
    if missing:
        raise SystemExit(f"Missing required inputs: {missing}")

    links = pd.read_csv(links_path, dtype={"link_id": str}, low_memory=False)
    links["hybrid_capacity_vph"] = pd.to_numeric(
        links["hybrid_capacity_vph"], errors="raise"
    )
    links["hybrid_capacity_per_lane_vphpl"] = pd.to_numeric(
        links["hybrid_capacity_per_lane_vphpl"], errors="raise"
    )
    segments, segment_ids = read_road_segments(
        network_path, set(links["link_id"])
    )
    order = pd.DataFrame({"link_id": segment_ids}).merge(
        links[
            [
                "link_id",
                "hybrid_capacity_vph",
                "hybrid_capacity_per_lane_vphpl",
                "final_permlanes",
            ]
        ],
        on="link_id",
        how="left",
        validate="one_to_one",
    )
    if order.isna().any().any():
        raise RuntimeError("Mapped road-capacity values contain missing data.")

    boundary = gpd.read_file(boundary_path).to_crs(MAP_CRS)
    minx, miny, maxx, maxy = boundary.total_bounds
    pad_x = (maxx - minx) * 0.025
    pad_y = (maxy - miny) * 0.035

    total_values = order["hybrid_capacity_vph"].to_numpy(float)
    per_lane_values = order[
        "hybrid_capacity_per_lane_vphpl"
    ].to_numpy(float)
    lanes = order["final_permlanes"].to_numpy(float)
    total_widths = 0.18 + 0.16 * np.sqrt(np.clip(lanes, 1, 8))
    lane_widths = np.full(len(order), 0.42)

    total_boundaries = [0, 1000, 1500, 2500, 4000, 6000, 8000, 12000]
    total_colors = [
        "#c9d6df",
        "#86b7c9",
        "#4f96b8",
        "#3a7d8c",
        "#e0a43a",
        "#d76a3a",
        "#a63d40",
    ]
    lane_boundaries = [0, 900, 1200, 1500, 1800, 2100, 2300]
    lane_colors = [
        "#d5e3d1",
        "#94c59a",
        "#56a58b",
        "#3c8494",
        "#e0a43a",
        "#c84f45",
    ]

    fig, axes = plt.subplots(1, 2, figsize=(18, 8.6), constrained_layout=True)
    for axis in axes:
        boundary.plot(
            ax=axis,
            facecolor="#f4f5f2",
            edgecolor="#6f7774",
            linewidth=0.45,
            zorder=0,
        )
        axis.set_xlim(minx - pad_x, maxx + pad_x)
        axis.set_ylim(miny - pad_y, maxy + pad_y)
        axis.set_aspect("equal")
        axis.set_axis_off()

    add_capacity_collection(
        axes[0],
        segments,
        total_values,
        total_boundaries,
        total_colors,
        total_widths,
        "Directional capacity (veh/h)",
    )
    axes[0].set_title(
        "Hong Kong hybrid road capacity",
        fontsize=15,
        fontweight="normal",
        pad=9,
    )
    axes[0].text(
        0.01,
        0.015,
        "Line width also reflects corrected directional lanes",
        transform=axes[0].transAxes,
        fontsize=9,
        color="#3f4846",
    )

    add_capacity_collection(
        axes[1],
        segments,
        per_lane_values,
        lane_boundaries,
        lane_colors,
        lane_widths,
        "Capacity per lane (veh/h/lane)",
    )
    axes[1].set_title(
        "Capacity normalized by corrected lanes",
        fontsize=15,
        fontweight="normal",
        pad=9,
    )
    source_legend = [
        Line2D(
            [0],
            [0],
            color="#6f7774",
            linewidth=0.8,
            label="Fixed-link model boundary",
        )
    ]
    axes[1].legend(
        handles=source_legend,
        loc="lower right",
        frameon=True,
        framealpha=0.9,
        fontsize=8,
    )

    fig.suptitle(
        "TPDM cross-section + observed-flow floors + corrected lanes",
        fontsize=11,
        fontweight="normal",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=240, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    if not output.exists() or output.stat().st_size < 100_000:
        raise RuntimeError("Capacity map output is missing or unexpectedly small.")
    print(
        {
            "output": str(output),
            "road_links": len(order),
            "capacity_min_vph": float(total_values.min()),
            "capacity_max_vph": float(total_values.max()),
            "capacity_per_lane_min_vphpl": float(per_lane_values.min()),
            "capacity_per_lane_max_vphpl": float(per_lane_values.max()),
        }
    )


if __name__ == "__main__":
    main()
