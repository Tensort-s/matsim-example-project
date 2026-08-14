#!/usr/bin/env python3
"""Extend exact TCS parking zones to the full activity-facility universe."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys

import geopandas as gpd
from lxml import etree as ET
import pandas as pd


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_hong_kong_student_school_od as school  # noqa: E402


ASSIGNMENT_METHOD = "point_within_adopted_study_area_and_dcca_classification"
SOURCE_NOTE = "census_study_areas+2021_DCCA+student_school_TCS_classifier"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facilities", type=Path, required=True)
    parser.add_argument("--car-feasibility", type=Path, required=True)
    parser.add_argument("--existing-repairs", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=school.DEFAULT_DATA_ROOT)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def parse_facilities(path: Path) -> pd.DataFrame:
    opener = gzip.open if path.suffix == ".gz" else open
    records: list[dict[str, object]] = []
    with opener(path, "rb") as handle:
        for _, facility in ET.iterparse(handle, events=("end",), tag="facility"):
            facility_id = facility.get("id", "")
            if not facility_id:
                raise ValueError("Activity facility lacks an id")
            records.append({
                "destination_facility_id": facility_id,
                "x": float(facility.get("x", "nan")),
                "y": float(facility.get("y", "nan")),
            })
            facility.clear()
            while facility.getprevious() is not None:
                del facility.getparent()[0]
    result = pd.DataFrame(records)
    if result.empty or result["destination_facility_id"].duplicated().any():
        raise ValueError("Facility input is empty or has duplicate ids")
    if not result[["x", "y"]].notna().all().all():
        raise ValueError("Facility input has missing coordinates")
    return result


def classify_missing(points: pd.DataFrame, data_root: Path) -> pd.DataFrame:
    paths = school.data_paths(data_root.resolve())
    for key in ("dcca_shp", "dcca_xlsx", "dc_shp", "newtown", "boundary"):
        if not paths[key].exists():
            raise FileNotFoundError(paths[key])
    dcca = school.read_dcca(paths)
    study_areas, _ = school.build_study_areas(
        paths["dc_shp"], paths["newtown"], paths["boundary"]
    )
    geo = gpd.GeoDataFrame(
        points.copy(), geometry=gpd.points_from_xy(points["x"], points["y"]),
        crs=school.WORK_CRS,
    )
    assigned = gpd.sjoin(geo, study_areas, predicate="within", how="left")
    # The adopted study-area layer intentionally contains small overlaps where
    # a New Town crosses an old District Council boundary. The school workflow
    # treats the New Town classification as the more specific TCS geography.
    # Resolve those exact within-overlaps deterministically; no nearest polygon
    # or default zone is introduced here.
    priority = {"new_town": 0, "dc_district": 1, "nt_other": 2}
    assigned["study_area_priority"] = assigned["study_area_type"].map(priority)
    if assigned["study_area_priority"].isna().any():
        raise ValueError("Facility intersects an unsupported study-area type")
    assigned = (
        assigned.sort_values(
            ["destination_facility_id", "study_area_priority", "study_area_id"]
        )
        .drop_duplicates("destination_facility_id", keep="first")
        .reset_index(drop=True)
    )
    if assigned["study_area_id"].isna().any():
        bad = assigned.loc[
            assigned["study_area_id"].isna(), "destination_facility_id"
        ].tolist()
        raise ValueError(f"Facilities are outside exact Census study areas: {bad[:20]}")
    assigned = gpd.sjoin(
        assigned.drop(columns=["index_right"], errors="ignore"),
        dcca.to_crs(school.WORK_CRS)[["dcca", "dcca_eng", "geometry"]],
        predicate="within",
        how="left",
        rsuffix="dcca",
    ).drop(columns=["index_right"], errors="ignore")
    assigned["dcca_eng"] = assigned["dcca_eng"].fillna("")
    required = ["dc", "dcca", "study_area_id"]
    if assigned[required].isna().any().any():
        bad = assigned.loc[
            assigned[required].isna().any(axis=1), "destination_facility_id"
        ].tolist()
        raise ValueError(f"Facilities lack exact Census/DCCA assignment: {bad[:20]}")
    assigned["tcs_zone"] = [
        school.classify_tcs_zone(int(dc), str(area), str(area_type), str(dcca_name))
        for dc, area, area_type, dcca_name in zip(
            assigned["dc"], assigned["study_area_name"],
            assigned["study_area_type"], assigned["dcca_eng"],
        )
    ]
    assigned["assignment_method"] = ASSIGNMENT_METHOD
    assigned["source_note"] = SOURCE_NOTE
    return assigned


def main() -> int:
    args = parse_args()
    facilities = parse_facilities(args.facilities)
    feasibility = pd.read_parquet(
        args.car_feasibility,
        columns=["destination_facility_id", "destination_tcs_zone"],
    )
    resolved = feasibility.loc[
        feasibility["destination_tcs_zone"].notna(),
        ["destination_facility_id", "destination_tcs_zone"],
    ].copy()
    variants = resolved.groupby("destination_facility_id")["destination_tcs_zone"].nunique()
    if (variants != 1).any():
        raise ValueError("Car feasibility has conflicting facility TCS zones")
    known = set(resolved["destination_facility_id"].astype(str))

    existing = pd.read_csv(args.existing_repairs, encoding="utf-8")
    columns = [
        "destination_facility_id", "tcs_zone", "dcca", "study_area_id",
        "assignment_method", "source_note",
    ]
    existing = existing[columns].copy()
    existing_ids = set(existing["destination_facility_id"].astype(str))
    missing_all = facilities.loc[
        ~facilities["destination_facility_id"].isin(known | existing_ids)
    ].copy()
    unresolved_border = missing_all.loc[
        missing_all["destination_facility_id"].str.startswith("border_")
    ].copy()
    missing = missing_all.drop(index=unresolved_border.index)
    classified = classify_missing(missing, args.data_root) if len(missing) else missing
    supplemental = (
        classified[columns].copy() if len(classified)
        else pd.DataFrame(columns=columns)
    )
    combined = pd.concat([existing, supplemental], ignore_index=True)
    if combined["destination_facility_id"].duplicated().any():
        raise ValueError("Combined parking-zone table has duplicate facilities")
    if not combined["tcs_zone"].between(1, 26).all():
        raise ValueError("Combined parking-zone table has an invalid TCS zone")
    combined = combined.sort_values("destination_facility_id").reset_index(drop=True)

    covered = known | set(combined["destination_facility_id"].astype(str))
    omitted = sorted(set(facilities["destination_facility_id"].astype(str)) - covered)
    expected_omitted = sorted(
        unresolved_border["destination_facility_id"].astype(str).tolist()
    )
    if omitted != expected_omitted:
        raise ValueError(f"Non-border facility universe remains uncovered: {omitted[:20]}")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.output_csv, index=False, encoding="utf-8", lineterminator="\n")
    report = {
        "status": "prepared_exact_open_innovation_parking_zones",
        "activity_facilities": len(facilities),
        "facilities_resolved_by_car_feasibility": int(
            facilities["destination_facility_id"].isin(known).sum()
        ),
        "facilities_resolved_by_existing_repairs": int(
            facilities["destination_facility_id"].isin(existing_ids).sum()
        ),
        "new_exact_spatial_assignments": len(supplemental),
        "combined_zone_rows": len(combined),
        "explicitly_unresolved_border_facilities": expected_omitted,
        "uncovered_nonborder_activity_facilities": len(
            set(omitted) - set(expected_omitted)
        ),
        "assignment_method": ASSIGNMENT_METHOD,
        "default_or_nearest_tcs_zone_fallback": False,
        "inputs": {
            "facilities": str(args.facilities),
            "car_feasibility": str(args.car_feasibility),
            "existing_repairs": str(args.existing_repairs),
        },
        "output": str(args.output_csv),
    }
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
