#!/usr/bin/env python3
"""Audit Hong Kong taxi controls against the current 5% initial MATSim plans."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = WINDOWS_ROOT if WINDOWS_ROOT.exists() else ROOT
DATA_ROOT = PROJECT_ROOT / "data"
RAW_DIR = DATA_ROOT / "taxi/hongkong/raw/monthly_traffic_transport_digest_2026"
V2_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
V1_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v1"
OUT_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_initial_plan_audit_2026_jan_jun"

MONTHS = [f"2026{month:02d}" for month in range(1, 7)]
SAMPLE_RATE = 0.05
EXPANSION = 20.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--v1-dir", type=Path, default=V1_DIR)
    parser.add_argument("--v2-dir", type=Path, default=V2_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--sample-rate", type=float, default=SAMPLE_RATE)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_source_manifest(raw_dir: Path, out_dir: Path) -> None:
    rows = []
    original_base = Path(r"D:\Program Files")
    for path in sorted(raw_dir.iterdir()):
        if path.is_file() and path.name != "SOURCE_MANIFEST.csv":
            rows.append(
                {
                    "file_name": path.name,
                    "project_path": path.as_posix(),
                    "original_download_path": (original_base / path.name).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = pd.DataFrame(rows)
    manifest.to_csv(raw_dir / "SOURCE_MANIFEST.csv", index=False, encoding="utf-8-sig")
    manifest.to_csv(out_dir / "SOURCE_MANIFEST.csv", index=False, encoding="utf-8-sig")


def read_csv(raw_dir: Path, name: str) -> pd.DataFrame:
    path = raw_dir / name
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str)


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def official_daily_control(raw_dir: Path, sample_rate: float) -> pd.DataFrame:
    avg = read_csv(raw_dir, "table21s_eng.csv")
    pax = read_csv(raw_dir, "table21_eng.csv")
    fleet = read_csv(raw_dir, "table22_eng.csv")

    avg = avg.loc[avg["YR_MTH"].isin(MONTHS) & avg["TTD_PTO_CODE"].eq("TAX")].copy()
    pax = pax.loc[pax["YR_MTH"].isin(MONTHS) & pax["TTD_PTO_CODE"].eq("TAX")].copy()
    fleet = fleet.loc[fleet["YR_MTH"].isin(MONTHS) & fleet["TTD_PTO_CODE"].eq("TAX")].copy()

    for table_name, frame in {
        "table21s_eng.csv": avg,
        "table21_eng.csv": pax,
        "table22_eng.csv": fleet,
    }.items():
        duplicate_months = frame["YR_MTH"].value_counts()
        duplicate_months = duplicate_months.loc[duplicate_months.gt(1)]
        if not duplicate_months.empty:
            raise ValueError(f"Expected one TAX row per month in {table_name}: {duplicate_months.to_dict()}")

    avg["avg_daily_pax_actual"] = numeric(avg["AVG_DAILY_PAX"]) * 1000.0
    pax["monthly_pax_actual"] = numeric(pax["PAX"]) * 1000.0
    fleet["no_fleet"] = numeric(fleet["NO_FLEET"])
    fleet["pax_cap"] = numeric(fleet["PAX_CAP"])

    control = (
        avg[["YR_MTH", "MODE", "TTD_PTO_CODE", "AVG_DAILY_PAX", "avg_daily_pax_actual"]]
        .merge(pax[["YR_MTH", "PAX", "monthly_pax_actual"]], on="YR_MTH", how="inner", validate="one_to_one")
        .merge(
            fleet[["YR_MTH", "NO_FLEET", "no_fleet", "PAX_CAP", "pax_cap"]],
            on="YR_MTH",
            how="inner",
            validate="one_to_one",
        )
        .sort_values("YR_MTH")
        .reset_index(drop=True)
    )
    if control.empty:
        raise ValueError("No overlapping 2026 TAX months found in Tables 2.1S, 2.1, and 2.2")
    missing_months = sorted(set(MONTHS) - set(control["YR_MTH"].astype(str)))
    control["daily_pax_per_taxi"] = control["avg_daily_pax_actual"] / control["no_fleet"]
    control["pax_cap_per_fleet_vehicle"] = control["pax_cap"] / control["no_fleet"]
    control["model_5pct_daily_pax_target"] = control["avg_daily_pax_actual"] * float(sample_rate)
    control["requested_period"] = "202601-202606"
    control["available_official_control_months"] = ",".join(control["YR_MTH"].astype(str))
    control["missing_official_control_months"] = ",".join(missing_months)
    control["unit_note"] = (
        "AVG_DAILY_PAX and PAX source units are thousand passenger journeys; "
        "actual columns multiply by 1000. NO_FLEET is month-end operating fleet."
    )
    return control


def taxi_fleet_by_type(raw_dir: Path) -> pd.DataFrame:
    table = read_csv(raw_dir, "table41a_eng.csv")
    rows = table.loc[table["YR_MTH"].isin(MONTHS) & table["TTD_PTO_CODE"].eq("TAX")].copy()
    rows = rows.loc[rows["TAXIS_TYPE_CODE"].isin(["Urban", "NT", "Lantau"])].copy()
    if rows.empty:
        raise ValueError("No TTD_PTO_CODE=TAX rows with Urban/NT/Lantau TAXIS_TYPE_CODE")

    for column in ["FIRST_REG", "TOTAL_REG", "TOTAL_LIC"]:
        rows[column.lower()] = numeric(rows[column]).fillna(0)
    grouped = (
        rows.groupby(["YR_MTH", "TAXIS_TYPE_CODE"], as_index=False)
        .agg(
            total_lic=("total_lic", "sum"),
            total_reg=("total_reg", "sum"),
            first_reg_reference_only=("first_reg", "sum"),
        )
        .rename(columns={"TAXIS_TYPE_CODE": "taxi_type"})
        .sort_values(["YR_MTH", "taxi_type"])
    )
    totals = (
        grouped.groupby("YR_MTH", as_index=False)
        .agg(
            taxi_type=("taxi_type", lambda _: "All licensed taxi types"),
            total_lic=("total_lic", "sum"),
            total_reg=("total_reg", "sum"),
            first_reg_reference_only=("first_reg_reference_only", "sum"),
        )
    )
    output = pd.concat([grouped, totals], ignore_index=True).sort_values(["YR_MTH", "taxi_type"])
    output["fleet_definition_note"] = (
        "TOTAL_LIC is used for licensed taxi counts by Urban/NT/Lantau type; "
        "FIRST_REG is retained only as a reference field and is not used as fleet size."
    )
    return output.reset_index(drop=True)


def count_plan_leg_modes(plans_path: Path) -> dict[str, int]:
    if not plans_path.exists():
        raise FileNotFoundError(plans_path)
    counts: dict[str, int] = {}
    with gzip.open(plans_path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag == "leg":
                mode = elem.attrib.get("mode", "")
                counts[mode] = counts.get(mode, 0) + 1
            elem.clear()
    return counts


def classify_ride(row: pd.Series) -> str:
    if bool(row["is_discretionary"]):
        return "unspecified_ride"
    detail = str(row.get("mode_detail", "") or "")
    if detail == "taxi":
        return "taxi"
    if detail in {"private_car_passenger_van", "private_vehicle"}:
        return "private_car_passenger"
    if detail == "spb":
        return "school_bus"
    return "unspecified_ride"


def current_plan_audit(v1_dir: Path, v2_dir: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    manifest = pd.read_parquet(v2_dir / "agent_trip_manifest_v2.parquet")
    v1_manifest = pd.read_parquet(v1_dir / "agent_trip_manifest.parquet")
    assignments = pd.read_parquet(v2_dir / "resident_discretionary_activity_assignments.parquet")

    required = {"person_id", "leg_sequence", "population_group", "role", "mode", "is_discretionary"}
    if missing := sorted(required - set(manifest.columns)):
        raise ValueError(f"agent_trip_manifest_v2 missing required columns: {missing}")
    if "mode_detail" not in v1_manifest.columns:
        raise ValueError("v1 agent_trip_manifest.parquet must include mode_detail")

    v1_detail = v1_manifest[["person_id", "leg_sequence", "mode_detail"]].copy()
    merged = manifest.merge(v1_detail, on=["person_id", "leg_sequence"], how="left")
    discretionary_modes = assignments[["person_id", "initial_discretionary_mode"]].copy()
    merged = merged.merge(discretionary_modes, on="person_id", how="left")

    ride = merged.loc[merged["mode"].eq("ride")].copy()
    ride["mode_detail"] = ride["mode_detail"].fillna("")
    ride["ride_subtype"] = ride.apply(classify_ride, axis=1)
    ride["source_detail"] = np.where(
        ride["is_discretionary"],
        "v2_discretionary_initial_mode",
        np.where(ride["mode_detail"].ne(""), "v1_mode_detail", "missing_or_external_detail"),
    )
    ride["legs_5pct"] = 1
    ride["expanded_passenger_legs"] = EXPANSION

    audit = (
        ride.groupby(
            ["ride_subtype", "population_group", "role", "is_discretionary", "source_detail", "mode_detail"],
            dropna=False,
            as_index=False,
        )
        .agg(
            legs_5pct=("legs_5pct", "sum"),
            expanded_passenger_legs=("expanded_passenger_legs", "sum"),
            persons=("person_id", "nunique"),
        )
        .sort_values(["ride_subtype", "population_group", "role", "is_discretionary", "mode_detail"])
    )

    plan_counts = count_plan_leg_modes(v2_dir / "plans_unrouted_5pct_v2.xml.gz")
    manifest_mode_counts = manifest["mode"].value_counts().to_dict()
    if int(plan_counts.get("ride", 0)) != int(manifest_mode_counts.get("ride", 0)):
        raise ValueError(
            "plans_unrouted_5pct_v2.xml.gz ride leg count does not match agent_trip_manifest_v2.parquet"
        )
    return audit.reset_index(drop=True), plan_counts


def write_gap_summary(
    official: pd.DataFrame,
    audit: pd.DataFrame,
    fleet_by_type: pd.DataFrame,
    plan_counts: dict[str, int],
    out_dir: Path,
    sample_rate: float,
) -> None:
    subtype_counts = audit.groupby("ride_subtype", as_index=True)["legs_5pct"].sum().to_dict()
    explicit_taxi = int(subtype_counts.get("taxi", 0))
    unspecified = int(subtype_counts.get("unspecified_ride", 0))
    total_ride = int(audit["legs_5pct"].sum())
    available_target = float(official["model_5pct_daily_pax_target"].mean())
    latest = official.iloc[-1]
    latest_fleet = fleet_by_type.loc[
        fleet_by_type["YR_MTH"].eq(str(latest["YR_MTH"]))
        & fleet_by_type["taxi_type"].eq("All licensed taxi types")
    ].iloc[0]

    summary = {
        "scenario": "hong_kong_taxi_initial_plan_audit_2026_jan_jun",
        "sample_rate": sample_rate,
        "requested_months": MONTHS,
        "available_official_control_months": [str(value) for value in official["YR_MTH"].tolist()],
        "missing_official_control_months": sorted(set(MONTHS) - set(official["YR_MTH"].astype(str))),
        "official_target_definition": "AVG_DAILY_PAX * 1000 * 0.05, using TTD_PTO_CODE=TAX rows from Table 2.1S.",
        "fleet_definition": {
            "operating_fleet": "Table 2.2 NO_FLEET, not FIRST_REG.",
            "licensed_fleet_by_type": "Table 4.1(a) TOTAL_LIC for Urban, NT, and Lantau taxis.",
            "capacity_check": "PAX_CAP / NO_FLEET is only an average per-fleet-vehicle passenger-capacity check.",
        },
        "official_5pct_daily_target": {
            "available_month_mean": available_target,
            "min": float(official["model_5pct_daily_pax_target"].min()),
            "max": float(official["model_5pct_daily_pax_target"].max()),
            "latest_month": str(latest["YR_MTH"]),
            "latest_month_target": float(latest["model_5pct_daily_pax_target"]),
            "latest_month_no_fleet": float(latest["no_fleet"]),
            "latest_month_total_lic_all_types": float(latest_fleet["total_lic"]),
        },
        "current_initial_plan_5pct_ride_legs": {
            "total_ride": total_ride,
            "explicit_taxi": explicit_taxi,
            "private_car_passenger": int(subtype_counts.get("private_car_passenger", 0)),
            "school_bus": int(subtype_counts.get("school_bus", 0)),
            "unspecified_ride": unspecified,
            "plan_leg_mode_counts": {str(k): int(v) for k, v in sorted(plan_counts.items())},
        },
        "gap_vs_official_available_month_mean": {
            "explicit_taxi_gap_5pct_legs_per_day": available_target - explicit_taxi,
            "explicit_taxi_gap_expanded_passenger_legs_per_day": (available_target - explicit_taxi) * EXPANSION,
            "gap_if_all_unspecified_ride_reclassified_to_taxi_5pct_legs_per_day": available_target
            - explicit_taxi
            - unspecified,
        },
        "classification_notes": [
            "Only mode_detail == taxi is counted as explicit taxi.",
            "private_vehicle and private_car_passenger_van are classified as private_car_passenger.",
            "spb is classified as school_bus.",
            "All discretionary ride legs and visitor_tcs_proxy ride legs are classified as unspecified_ride.",
            "No existing plans.xml.gz file is modified by this audit.",
        ],
        "outputs": {
            "taxi_official_daily_control.csv": "Official Table 2.1S/2.1/2.2 TAX controls with thousand-unit conversions.",
            "taxi_fleet_by_type.csv": "Table 4.1(a) TOTAL_LIC by Urban/NT/Lantau taxi type.",
            "taxi_initial_plan_audit.csv": "Current v2 initial-plan ride legs split by subtype and population group.",
            "SOURCE_MANIFEST.csv": "Project-local copies and SHA256 hashes of downloaded source files.",
        },
    }
    (out_dir / "taxi_initial_plan_gap_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    write_source_manifest(args.raw_dir, out_dir)
    official = official_daily_control(args.raw_dir, args.sample_rate)
    fleet = taxi_fleet_by_type(args.raw_dir)
    audit, plan_counts = current_plan_audit(args.v1_dir, args.v2_dir)

    official.to_csv(out_dir / "taxi_official_daily_control.csv", index=False, encoding="utf-8-sig")
    fleet.to_csv(out_dir / "taxi_fleet_by_type.csv", index=False, encoding="utf-8-sig")
    audit.to_csv(out_dir / "taxi_initial_plan_audit.csv", index=False, encoding="utf-8-sig")
    write_gap_summary(official, audit, fleet, plan_counts, out_dir, args.sample_rate)

    print(
        json.dumps(
            {
                "out_dir": out_dir.as_posix(),
                "official_rows": len(official),
                "fleet_rows": len(fleet),
                "audit_rows": len(audit),
                "ride_legs_in_initial_plans": int(sum(audit["legs_5pct"])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
