#!/usr/bin/env python3
"""Extend exact TCS parking zones to all full-day driver-switch destinations."""

from __future__ import annotations

import argparse
import csv
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
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--car-feasibility", type=Path, required=True)
    parser.add_argument("--existing-repairs", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=school.DEFAULT_DATA_ROOT)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def selected_plan(person: ET._Element) -> ET._Element:
    plans = [item for item in person if local_name(item) == "plan"]
    selected = [item for item in plans if item.get("selected") == "yes"]
    if len(selected) != 1:
        raise ValueError(f"Person {person.get('id')} has {len(selected)} selected plans")
    return selected[0]


def driver_switch_people(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["driver_person_id"] for row in rows
        if row["driver_requires_car_switch"].lower() == "true"
    }


def parse_destinations(path: Path, drivers: set[str]) -> pd.DataFrame:
    records: dict[str, dict[str, object]] = {}
    seen_drivers: set[str] = set()
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), tag="person")
        for _, person in context:
            person_id = person.get("id", "")
            if person_id not in drivers:
                person.clear()
                continue
            seen_drivers.add(person_id)
            activities = [
                item for item in selected_plan(person)
                if local_name(item) == "activity"
                and not item.get("type", "").endswith(" interaction")
            ]
            if len(activities) < 2:
                raise ValueError(f"Driver {person_id} has no complete main trip")
            if not activities[0].get("type", "").startswith("home") \
                    or not activities[-1].get("type", "").startswith("home"):
                raise ValueError(f"Driver {person_id} does not have a home-based day")
            for activity in activities[1:]:
                facility = activity.get("facility", "")
                if not facility:
                    raise ValueError(f"Driver {person_id} destination lacks facility")
                record = {
                    "destination_facility_id": facility,
                    "destination_activity_type": activity.get("type", ""),
                    "x": float(activity.get("x", "nan")),
                    "y": float(activity.get("y", "nan")),
                }
                previous = records.get(facility)
                if previous is not None and (
                    previous["x"] != record["x"] or previous["y"] != record["y"]
                    or previous["destination_activity_type"]
                    != record["destination_activity_type"]
                ):
                    raise ValueError(f"Facility has conflicting coordinates: {facility}")
                records[facility] = record
            person.clear()
            while person.getprevious() is not None:
                del person.getparent()[0]
    if seen_drivers != drivers:
        missing = sorted(drivers - seen_drivers)
        raise ValueError(f"Candidate drivers absent from plans: {missing[:20]}")
    return pd.DataFrame(records.values())


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
    assigned = school.assign_point_areas(geo, study_areas, dcca)
    missing_area = assigned["dc"].isna()
    if missing_area.any():
        recovered_dc = (
            pd.to_numeric(assigned.loc[missing_area, "dcca"], errors="coerce") // 100
        ).astype("Int64")
        assigned.loc[missing_area, "dc"] = recovered_dc.to_numpy()
        assigned.loc[missing_area, "study_area_id"] = [
            f"nt_other_dc_{int(code)}" if pd.notna(code) else "nt_other_unknown"
            for code in recovered_dc
        ]
        assigned.loc[missing_area, "study_area_name"] = "other NT area"
        assigned.loc[missing_area, "study_area_type"] = "nt_other"
    if assigned[["dc", "dcca", "study_area_id"]].isna().any().any():
        bad = assigned.loc[
            assigned[["dc", "dcca", "study_area_id"]].isna().any(axis=1),
            "destination_facility_id",
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
    drivers = driver_switch_people(args.candidates)
    destinations = parse_destinations(args.plans, drivers)
    feasibility = pd.read_parquet(
        args.car_feasibility,
        columns=["destination_facility_id", "destination_tcs_zone"],
    )
    known = set(feasibility.loc[
        feasibility["destination_tcs_zone"].notna(), "destination_facility_id"
    ].astype(str))
    existing = pd.read_csv(args.existing_repairs, encoding="utf-8")
    existing_ids = set(existing["destination_facility_id"].astype(str))
    missing_all = destinations.loc[
        ~destinations["destination_facility_id"].isin(known | existing_ids)
    ].copy()
    unresolved_border = missing_all.loc[
        missing_all["destination_activity_type"].str.startswith("border")
    ].copy()
    missing = missing_all.drop(index=unresolved_border.index)
    classified = classify_missing(missing, args.data_root) if len(missing) else missing
    columns = [
        "destination_facility_id", "tcs_zone", "dcca", "study_area_id",
        "assignment_method", "source_note",
    ]
    supplemental = classified[columns].copy() if len(classified) else pd.DataFrame(columns=columns)
    combined = pd.concat([existing[columns], supplemental], ignore_index=True)
    if combined["destination_facility_id"].duplicated().any():
        raise ValueError("Combined parking-zone table has duplicate facilities")
    if not combined["tcs_zone"].between(1, 26).all():
        raise ValueError("Combined parking-zone table has an invalid TCS zone")
    combined = combined.sort_values("destination_facility_id").reset_index(drop=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.output_csv, index=False, encoding="utf-8", lineterminator="\n")
    report = {
        "status": "prepared_exact_household_joint_driver_switch_parking_zones",
        "driver_switch_people": len(drivers),
        "driver_day_destination_facilities": len(destinations),
        "already_in_car_feasibility": int(destinations["destination_facility_id"].isin(known).sum()),
        "already_in_original_repairs": int(destinations["destination_facility_id"].isin(existing_ids).sum()),
        "new_exact_spatial_assignments": len(supplemental),
        "explicitly_unresolved_border_facilities": sorted(
            unresolved_border["destination_facility_id"].astype(str).tolist()
        ),
        "combined_zone_rows": len(combined),
        "assignment_method": ASSIGNMENT_METHOD,
        "default_or_nearest_tcs_zone_fallback": False,
        "school_bus_scope": False,
        "inputs": {
            "plans": str(args.plans),
            "candidates": str(args.candidates),
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
