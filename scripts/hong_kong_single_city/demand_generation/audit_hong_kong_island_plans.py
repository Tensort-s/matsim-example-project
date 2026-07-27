#!/usr/bin/env python3
"""Audit Hong Kong MATSim plans for internal activities outside fixed-link land."""

from __future__ import annotations

import argparse
import gzip
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(r"F:\Matsim\matsim-example-project"),
    )
    parser.add_argument("--plans", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def main() -> None:
    args = parse_args()
    root = args.project_root.resolve()
    plans = args.plans or (
        root
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v1/plans_unrouted_5pct.xml.gz"
    )
    output_dir = args.output_dir or (
        root
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v1/validation/fixed_link_island_audit"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = (
        root
        / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
    )
    boundary = gpd.read_file(boundary_path).to_crs(32650).geometry.union_all()

    rows: list[dict[str, Any]] = []
    person_id = ""
    attributes: dict[str, str] = {}
    activity_index = 0
    with gzip.open(plans, "rb") as handle:
        for event, elem in ET.iterparse(handle, events=("start", "end")):
            tag = local_name(elem.tag)
            if event == "start" and tag == "person":
                person_id = elem.attrib["id"]
                attributes = {}
                activity_index = 0
            elif event == "end" and tag == "attribute":
                attributes[elem.attrib.get("name", "")] = elem.text or ""
            elif event == "end" and tag == "activity":
                x = elem.attrib.get("x")
                y = elem.attrib.get("y")
                if x is not None and y is not None:
                    rows.append(
                        {
                            "person_id": person_id,
                            "activity_index": activity_index,
                            "activity_type": elem.attrib.get("type", ""),
                            "facility_id": elem.attrib.get("facility", ""),
                            "x": float(x),
                            "y": float(y),
                            "subpopulation": attributes.get("subpopulation", ""),
                            "role": attributes.get("role", ""),
                            "mode_detail": attributes.get("modeDetail", ""),
                        }
                    )
                activity_index += 1
            elif event == "end" and tag == "person":
                elem.clear()

    frame = pd.DataFrame(rows)
    inside = shapely.intersects_xy(
        boundary,
        frame["x"].to_numpy(dtype=float),
        frame["y"].to_numpy(dtype=float),
    )
    outside = frame.loc[~inside].copy()
    outside["is_explicit_border_activity"] = outside["activity_type"].eq("border")
    internal_outside = outside.loc[~outside["is_explicit_border_activity"]].copy()
    ferry_agents = frame.loc[
        frame["mode_detail"].str.contains("ferry|vessel", case=False, na=False),
        "person_id",
    ].nunique()

    outside.to_csv(
        output_dir / "outside_fixed_link_activities.csv",
        index=False,
        encoding="utf-8-sig",
    )
    internal_outside.to_csv(
        output_dir / "internal_island_activities_requiring_correction.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary = {
        "plans": str(plans),
        "boundary": str(boundary_path),
        "persons": int(frame["person_id"].nunique()),
        "activities": int(len(frame)),
        "outside_fixed_link_activities": int(len(outside)),
        "outside_fixed_link_persons": int(outside["person_id"].nunique()),
        "explicit_border_activities_outside": int(
            outside["is_explicit_border_activity"].sum()
        ),
        "internal_island_activities_requiring_correction": int(len(internal_outside)),
        "internal_island_persons_requiring_correction": int(
            internal_outside["person_id"].nunique()
        ),
        "ferry_labeled_agents": int(ferry_agents),
        "correction_performed": False,
        "correction_reason": (
            "No internal activity lies outside the fixed-link boundary; only explicit "
            "cross-border activities are outside. Rewriting plans would be incorrect."
            if internal_outside.empty
            else "Internal outside-boundary activities exist and require destination-specific correction."
        ),
        "outside_activity_types": {
            str(key): int(value)
            for key, value in Counter(outside["activity_type"]).items()
        },
        "qa_passed": bool(internal_outside.empty),
    }
    (output_dir / "fixed_link_island_plan_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not internal_outside.empty:
        raise RuntimeError(
            f"{len(internal_outside)} internal activities require correction; "
            "see internal_island_activities_requiring_correction.csv"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
