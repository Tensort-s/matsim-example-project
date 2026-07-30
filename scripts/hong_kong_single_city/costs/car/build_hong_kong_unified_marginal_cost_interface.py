#!/usr/bin/env python3
"""Build the audited Hong Kong private-car marginal-cost interface v1.

Only the independently audited energy, toll, and destination-parking
candidates enter leg-level marginal totals. Fixed vehicle-ownership cost is
referenced as an accounting sidecar and is never joined to a leg.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
import pandas as pd


CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
DEFAULT_OUTPUT = CAR_COST_ROOT / "unified_marginal_cost_interface_v1"
SOURCE_COMMIT = "f3fa7b6ad510929d087da29df32d5f2be375e5eb"
CANDIDATE_BUILD_DATE = "2026-07-29"
SCENARIOS = ("low", "base", "high")
COMPONENTS = (
    "fuel_or_electricity",
    "toll",
    "destination_parking",
)
KEY_COLUMNS = ["person_id", "leg_sequence"]
IDENTITY_COLUMNS = [
    "person_id",
    "leg_sequence",
    "mode",
    "vehicle_ref_id",
    "vehicle_class",
]
FLOAT_TOLERANCE = 1e-9

ENERGY_ROOT = CAR_COST_ROOT / "energy_application_v1"
TOLL_MAPPING_ROOT = CAR_COST_ROOT / "toll_network_mapping_v1"
TOLL_ROOT = CAR_COST_ROOT / "toll_rate_application_v1"
PARKING_ROOT = CAR_COST_ROOT / "parking_event_application_v1"
FIXED_ROOT = CAR_COST_ROOT / "fixed_ownership_application_v1"
FEASIBILITY_PATH = (
    CAR_COST_ROOT
    / "input_feasibility/car_leg_input_feasibility.parquet"
)
SOURCE_MANIFEST_PATH = CAR_COST_ROOT / "car_cost_source_manifest.json"

COMPONENT_LONG_COLUMNS = [
    "person_id",
    "leg_sequence",
    "mode",
    "vehicle_ref_id",
    "vehicle_class",
    "scenario",
    "cost_component",
    "cost_hkd",
    "cost_status",
    "cost_source",
    "cost_effective_date",
    "cost_quality",
    "source_snapshot_sha256",
    "scenario_semantics",
    "candidate_build_date",
    "candidate_build_date_semantics",
    "record_scope",
    "cost_nature",
    "incremental_if_car_leg_chosen",
    "behavioral_inclusion_current_model",
    "eligible_for_future_scoring_pilot",
    "eligible_for_matsim_scoring",
    "unresolved_reason",
    "source_candidate_path",
    "source_candidate_sha256",
    "route_distance_m",
    "distance_band",
    "destination_activity_group",
    "fixed_vehicle_ownership_cost_included",
]

LEG_SUMMARY_COLUMNS = [
    "person_id",
    "leg_sequence",
    "mode",
    "vehicle_ref_id",
    "vehicle_class",
    "scenario",
    "route_distance_m",
    "distance_band",
    "destination_activity_group",
    "fuel_or_electricity_hkd",
    "fuel_or_electricity_status",
    "toll_hkd",
    "toll_status",
    "destination_parking_hkd",
    "destination_parking_status",
    "resolved_component_count",
    "required_component_count",
    "marginal_cost_complete",
    "behavioral_inclusion_current_model",
    "behavioral_marginal_cost_hkd",
    "unresolved_reason",
    "fixed_vehicle_ownership_cost_included",
    "fixed_vehicle_ownership_cost_hkd",
    "candidate_output_only",
    "scoring_adoption_approved",
    "joint_mode_choice_calibration_approved",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root containing read-only MATSim inputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    return parser.parse_args()


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file()
    )
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def hash_map(paths: dict[str, Path]) -> dict[str, str]:
    return {
        key: sha256_file(path)
        for key, path in sorted(paths.items())
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def canonical_paths(input_root: Path) -> dict[str, Path]:
    demand = (
        input_root
        / "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice"
    )
    supply = (
        input_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010"
    )
    result = {
        "plans_routed": demand / "plans_routed_5pct_v2.xml.gz",
        "plans_unrouted": demand / "plans_unrouted_5pct_v2.xml.gz",
        "private_vehicles": demand / "privateVehicles_5pct.xml.gz",
        "facilities": demand / "facilities_5pct_v2.xml.gz",
        "trip_manifest": demand / "agent_trip_manifest_v2.parquet",
        "config": (
            demand
            / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ),
        "network": supply / "network.xml.gz",
        "transit_schedule": supply / "transitSchedule_5pct.xml.gz",
        "transit_vehicles": supply / "transitVehicles_10pct.xml.gz",
    }
    missing = [key for key, path in result.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical unified-interface inputs: {missing}"
        )
    return result


def protected_paths(output_dir: Path) -> dict[str, Path]:
    output_resolved = output_dir.resolve()
    result: dict[str, Path] = {}
    for path in CAR_COST_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve().is_relative_to(output_resolved):
            continue
        result[path.as_posix()] = path
    return result


def candidate_roots() -> dict[str, Path]:
    return {
        "energy_application_v1": ENERGY_ROOT,
        "toll_network_mapping_v1": TOLL_MAPPING_ROOT,
        "toll_rate_application_v1": TOLL_ROOT,
        "parking_event_application_v1": PARKING_ROOT,
        "fixed_ownership_application_v1": FIXED_ROOT,
    }


def candidate_bundles() -> dict[str, str]:
    return {
        key: sha256_directory(path)
        for key, path in candidate_roots().items()
    }


def component_path(component: str, scenario: str) -> Path:
    if component == "fuel_or_electricity":
        return (
            ENERGY_ROOT
            / f"car_leg_energy_cost_estimates_{scenario}.parquet"
        )
    if component == "toll":
        return (
            TOLL_ROOT
            / f"car_leg_toll_cost_estimates_{scenario}.parquet"
        )
    if component == "destination_parking":
        return (
            PARKING_ROOT
            / f"car_leg_parking_cost_estimates_{scenario}.parquet"
        )
    raise ValueError(component)


def load_vehicle_classes(path: Path) -> dict[str, str]:
    vehicles: dict[str, str] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "vehicle":
                vehicle_id = str(element.attrib.get("id", "")).strip()
                vehicle_class = str(
                    element.attrib.get("type", "")
                ).strip()
                if vehicle_id in vehicles:
                    raise RuntimeError(
                        f"Duplicate vehicle definition {vehicle_id}"
                    )
                vehicles[vehicle_id] = vehicle_class
            element.clear()
    return vehicles


def normalized_identity(
    canonical: dict[str, Path],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = pd.read_parquet(
        canonical["trip_manifest"],
        columns=["person_id", "leg_sequence", "mode"],
    )
    manifest = manifest.loc[manifest["mode"].eq("car")].copy()
    manifest["person_id"] = manifest["person_id"].astype(str)
    manifest["leg_sequence"] = manifest["leg_sequence"].astype(int)
    if manifest.duplicated(KEY_COLUMNS).any():
        raise RuntimeError("Duplicate canonical car leg key in manifest")

    feasibility = pd.read_parquet(
        FEASIBILITY_PATH,
        columns=[
            "person_id",
            "leg_sequence",
            "manifest_mode",
            "vehicle_ref_id",
            "vehicle_class",
            "route_distance_m",
            "destination_activity_group",
        ],
    )
    feasibility["person_id"] = feasibility["person_id"].astype(str)
    feasibility["leg_sequence"] = feasibility["leg_sequence"].astype(int)
    if feasibility.duplicated(KEY_COLUMNS).any():
        raise RuntimeError(
            "Duplicate canonical car leg key in feasibility audit"
        )
    manifest_keys = set(
        zip(
            manifest["person_id"],
            manifest["leg_sequence"],
            strict=False,
        )
    )
    feasibility_keys = set(
        zip(
            feasibility["person_id"],
            feasibility["leg_sequence"],
            strict=False,
        )
    )
    if manifest_keys != feasibility_keys:
        raise RuntimeError(
            "Manifest and feasibility car leg key sets differ"
        )
    vehicle_classes = load_vehicle_classes(
        canonical["private_vehicles"]
    )
    resolved_class = feasibility["vehicle_ref_id"].map(
        vehicle_classes
    )
    if resolved_class.isna().any():
        raise RuntimeError(
            "Canonical feasibility vehicle reference is absent from "
            "privateVehicles"
        )
    if not resolved_class.eq(feasibility["vehicle_class"]).all():
        raise RuntimeError(
            "Canonical feasibility and privateVehicles classes conflict"
        )
    identity = feasibility.rename(
        columns={"manifest_mode": "mode"}
    )[
        IDENTITY_COLUMNS
        + ["route_distance_m", "destination_activity_group"]
    ].copy()
    identity = identity.sort_values(
        KEY_COLUMNS, kind="mergesort"
    ).reset_index(drop=True)
    identity["distance_band"] = identity["route_distance_m"].map(
        distance_band
    )
    return identity, {
        "manifest_car_leg_count": int(len(manifest)),
        "feasibility_car_leg_count": int(len(feasibility)),
        "canonical_key_sets_equal": True,
        "canonical_vehicle_reference_resolved_count": int(
            resolved_class.notna().sum()
        ),
        "canonical_vehicle_classes_match_private_vehicles": True,
    }


def distance_band(value: object) -> str:
    if value is None or pd.isna(value):
        return "distance_unavailable"
    distance = float(value)
    if distance < 0:
        return "distance_negative_unresolved"
    if distance == 0:
        return "zero_distance"
    if distance <= 5_000:
        return "gt0_to_5km"
    if distance <= 10_000:
        return "gt5_to_10km"
    if distance <= 20_000:
        return "gt10_to_20km"
    if distance <= 40_000:
        return "gt20_to_40km"
    return "gt40km"


def source_snapshot_hashes() -> dict[str, str]:
    energy_hashes = json.loads(
        (
            ENERGY_ROOT / "energy_application_input_hashes.json"
        ).read_text(encoding="utf-8")
    )["source_snapshot_manifest_checks"]
    energy_value = "|".join(
        str(energy_hashes[key]["actual_sha256"])
        for key in sorted(energy_hashes)
    )
    parking_rules = pd.read_csv(
        PARKING_ROOT / "parking_cost_rules_repository_relative.csv"
    )
    parking_values: set[str] = set()
    for value in parking_rules["file_sha256"].dropna().astype(str):
        parking_values.update(
            part for part in value.split("|") if part
        )
    source_manifest = json.loads(
        SOURCE_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    toll_value = str(
        source_manifest["machine_readable_toll_source"][
            "directory_sha256"
        ]
    )
    return {
        "fuel_or_electricity": energy_value,
        "toll": toll_value,
        "destination_parking": "|".join(sorted(parking_values)),
    }


def component_status_column(component: str) -> str:
    return {
        "fuel_or_electricity": "energy_status",
        "toll": "toll_status",
        "destination_parking": "parking_status",
    }[component]


def status_is_resolved(component: str, status: object) -> bool:
    value = str(status)
    if component == "fuel_or_electricity":
        return value.startswith("resolved_")
    if component == "toll":
        return value in {"confirmed_charge", "confirmed_no_charge"}
    if component == "destination_parking":
        return value.startswith("resolved_")
    return False


def status_is_out_of_scope(status: object) -> bool:
    return "out_of_scope" in str(status)


def scenario_semantics(component: str, scenario: str) -> str:
    if component == "fuel_or_electricity":
        return (
            f"{scenario}_joint_energy_price_and_consumption_sensitivity_"
            "representative_licensed_fleet_not_individual_powertrain"
        )
    if component == "toll":
        return (
            f"{scenario}_official_PC_rate_passage_time_sensitivity_"
            "official_day_type_A_typical_workday_no_calendar_date"
        )
    return (
        f"{scenario}_official_rate_bounded_zone_activity_duration_"
        "parking_proxy_not_observed_facility_tariff"
    )


def assert_candidate_validation() -> dict[str, Any]:
    files = {
        "energy": ENERGY_ROOT / "energy_application_validation.json",
        "toll": TOLL_ROOT / "toll_rate_application_validation.json",
        "parking": (
            PARKING_ROOT / "parking_event_application_validation.json"
        ),
        "fixed": (
            FIXED_ROOT / "fixed_ownership_application_validation.json"
        ),
    }
    result: dict[str, Any] = {}
    for key, path in files.items():
        validation = json.loads(path.read_text(encoding="utf-8"))
        if not validation.get("publishable_candidate", False):
            raise RuntimeError(f"{key} candidate is not publishable")
        if validation.get("blocked", True):
            raise RuntimeError(f"{key} candidate is blocked")
        result[key] = {
            "validation_path": path.as_posix(),
            "validation_sha256": sha256_file(path),
            "publishable_candidate": True,
            "blocked": False,
        }
    return result


def read_component(
    component: str,
    scenario: str,
    identity: pd.DataFrame,
    snapshot_hash: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = component_path(component, scenario)
    frame = pd.read_parquet(path)
    frame["person_id"] = frame["person_id"].astype(str)
    frame["leg_sequence"] = frame["leg_sequence"].astype(int)
    if len(frame) != 67_718:
        raise RuntimeError(
            f"{component}/{scenario} row count is {len(frame)}"
        )
    if frame.duplicated(KEY_COLUMNS).any():
        raise RuntimeError(
            f"{component}/{scenario} has duplicate person-leg keys"
        )
    if not frame["scenario"].eq(scenario).all():
        raise RuntimeError(
            f"{component}/{scenario} scenario column conflict"
        )
    reference_keys = set(
        zip(
            identity["person_id"],
            identity["leg_sequence"],
            strict=False,
        )
    )
    component_keys = set(
        zip(
            frame["person_id"],
            frame["leg_sequence"],
            strict=False,
        )
    )
    if component_keys != reference_keys:
        raise RuntimeError(
            f"{component}/{scenario} key set differs from canonical"
        )
    canonical_for_merge = identity.rename(
        columns={
            "mode": "mode_canonical",
            "vehicle_ref_id": "vehicle_ref_id_canonical",
            "vehicle_class": "vehicle_class_canonical",
            "route_distance_m": "route_distance_m_canonical",
            "destination_activity_group": (
                "destination_activity_group_canonical"
            ),
        }
    )
    aligned = canonical_for_merge.merge(
        frame,
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not aligned["_merge"].eq("both").all():
        raise RuntimeError(
            f"{component}/{scenario} produced a missing join"
        )
    if "mode" in aligned:
        if not aligned["mode"].eq(
            aligned["mode_canonical"]
        ).all():
            raise RuntimeError(
                f"{component}/{scenario} mode conflict"
            )
    for column in ("vehicle_ref_id", "vehicle_class"):
        candidate_column = column
        canonical_column = f"{column}_canonical"
        if candidate_column in aligned:
            if not aligned[candidate_column].eq(
                aligned[canonical_column]
            ).all():
                raise RuntimeError(
                    f"{component}/{scenario} {column} conflict"
                )
    status_column = component_status_column(component)
    resolved = aligned[status_column].map(
        lambda value: status_is_resolved(component, value)
    )
    out_of_scope = aligned[status_column].map(
        status_is_out_of_scope
    )
    unresolved = ~resolved & ~out_of_scope
    if aligned.loc[unresolved | out_of_scope, "cost_hkd"].notna().any():
        raise RuntimeError(
            f"{component}/{scenario} unresolved/out-of-scope cost is not null"
        )
    if aligned.loc[resolved, "cost_hkd"].isna().any():
        raise RuntimeError(
            f"{component}/{scenario} resolved cost is null"
        )

    output = pd.DataFrame(
        {
            "person_id": aligned["person_id"],
            "leg_sequence": aligned["leg_sequence"],
            "mode": aligned["mode_canonical"],
            "vehicle_ref_id": aligned["vehicle_ref_id_canonical"],
            "vehicle_class": aligned["vehicle_class_canonical"],
            "scenario": scenario,
            "cost_component": component,
            "cost_hkd": aligned["cost_hkd"],
            "cost_status": aligned[status_column],
            "cost_source": aligned["cost_source"],
            "cost_effective_date": aligned["cost_effective_date"],
            "cost_quality": aligned["cost_quality"],
            "source_snapshot_sha256": snapshot_hash,
            "scenario_semantics": scenario_semantics(
                component, scenario
            ),
            "candidate_build_date": CANDIDATE_BUILD_DATE,
            "candidate_build_date_semantics": (
                "interface_build_date_not_component_rate_effective_date"
            ),
            "record_scope": "leg_marginal_cost_component",
            "cost_nature": "trip_conditional_marginal_cost",
            "incremental_if_car_leg_chosen": True,
            "behavioral_inclusion_current_model": (
                resolved
                & aligned["vehicle_class_canonical"].eq("private_car")
            ),
            "eligible_for_future_scoring_pilot": (
                resolved
                & aligned["vehicle_class_canonical"].eq("private_car")
            ),
            "eligible_for_matsim_scoring": False,
            "unresolved_reason": aligned["unresolved_reason"],
            "source_candidate_path": path.as_posix(),
            "source_candidate_sha256": sha256_file(path),
            "route_distance_m": aligned["route_distance_m_canonical"],
            "distance_band": aligned["distance_band"],
            "destination_activity_group": aligned[
                "destination_activity_group_canonical"
            ],
            "fixed_vehicle_ownership_cost_included": False,
        }
    )
    diagnostics = {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "row_count": int(len(frame)),
        "person_leg_key_unique": True,
        "keys_match_canonical": True,
        "mode_matches_canonical": True,
        "vehicle_ref_id_field_present": (
            "vehicle_ref_id" in frame.columns
        ),
        "vehicle_class_field_present": (
            "vehicle_class" in frame.columns
        ),
        "vehicle_identity_matches_canonical_when_present": True,
        "resolved_count": int(resolved.sum()),
        "unresolved_count": int(unresolved.sum()),
        "out_of_scope_count": int(out_of_scope.sum()),
        "unresolved_and_out_of_scope_cost_null": True,
        "resolved_cost_non_null": True,
    }
    return output[COMPONENT_LONG_COLUMNS], diagnostics


def combine_reason(
    row: pd.Series,
    component: str,
    status_column: str,
    reason_column: str,
) -> str:
    status = row[status_column]
    if status_is_resolved(component, status):
        return ""
    reason = str(row[reason_column] or "").strip()
    return f"{component}:{reason if reason else status}"


def build_leg_summary(
    component_frames: dict[str, pd.DataFrame],
    scenario: str,
) -> pd.DataFrame:
    reference = component_frames["fuel_or_electricity"][
        IDENTITY_COLUMNS
        + ["route_distance_m", "distance_band", "destination_activity_group"]
    ].copy()
    result = reference
    for component in COMPONENTS:
        frame = component_frames[component][
            KEY_COLUMNS
            + ["cost_hkd", "cost_status", "unresolved_reason"]
        ].rename(
            columns={
                "cost_hkd": f"{component}_hkd",
                "cost_status": f"{component}_status",
                "unresolved_reason": f"{component}_unresolved_reason",
            }
        )
        result = result.merge(
            frame,
            on=KEY_COLUMNS,
            how="left",
            validate="one_to_one",
        )
    result["scenario"] = scenario
    resolved_flags = []
    for component in COMPONENTS:
        resolved_flags.append(
            result[f"{component}_status"].map(
                lambda value, name=component: status_is_resolved(
                    name, value
                )
            )
        )
    result["resolved_component_count"] = sum(resolved_flags)
    result["required_component_count"] = 3
    result["marginal_cost_complete"] = (
        result["vehicle_class"].eq("private_car")
        & result["resolved_component_count"].eq(3)
    )
    result["behavioral_inclusion_current_model"] = result[
        "marginal_cost_complete"
    ]
    result["behavioral_marginal_cost_hkd"] = np.nan
    complete = result["marginal_cost_complete"]
    result.loc[complete, "behavioral_marginal_cost_hkd"] = (
        result.loc[complete, "fuel_or_electricity_hkd"]
        + result.loc[complete, "toll_hkd"]
        + result.loc[complete, "destination_parking_hkd"]
    )
    reasons: list[str] = []
    for _, row in result.iterrows():
        parts = [
            combine_reason(
                row,
                component,
                f"{component}_status",
                f"{component}_unresolved_reason",
            )
            for component in COMPONENTS
        ]
        reasons.append("|".join(part for part in parts if part))
    result["unresolved_reason"] = reasons
    result["fixed_vehicle_ownership_cost_included"] = False
    result["fixed_vehicle_ownership_cost_hkd"] = np.nan
    result["candidate_output_only"] = True
    result["scoring_adoption_approved"] = False
    result["joint_mode_choice_calibration_approved"] = False
    return result[LEG_SUMMARY_COLUMNS]


def resolved_status_counts(
    component: str,
    frame: pd.DataFrame,
) -> tuple[int, int, int]:
    resolved = frame["cost_status"].map(
        lambda value: status_is_resolved(component, value)
    )
    out_of_scope = frame["cost_status"].map(
        status_is_out_of_scope
    )
    unresolved = ~resolved & ~out_of_scope
    return (
        int(resolved.sum()),
        int(unresolved.sum()),
        int(out_of_scope.sum()),
    )


def statistics(values: pd.Series) -> dict[str, float]:
    clean = values.dropna().astype(float)
    if clean.empty:
        return {
            "mean_hkd": float("nan"),
            "median_hkd": float("nan"),
            "p90_hkd": float("nan"),
        }
    return {
        "mean_hkd": float(clean.mean()),
        "median_hkd": float(clean.median()),
        "p90_hkd": float(clean.quantile(0.9)),
    }


def blank_summary_row(scenario: str) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "summary_dimension": "",
        "group_value": "",
        "cost_component": "",
        "record_count": 0,
        "private_car_count": 0,
        "motorcycle_count": 0,
        "resolved_count": 0,
        "unresolved_count": 0,
        "out_of_scope_count": 0,
        "complete_private_car_count": 0,
        "incomplete_private_car_count": 0,
        "resolved_only_total_hkd": float("nan"),
        "complete_behavioral_total_hkd": float("nan"),
        "accounting_sidecar_total_hkd": float("nan"),
        "mean_hkd": float("nan"),
        "median_hkd": float("nan"),
        "p90_hkd": float("nan"),
        "included_in_behavioral_marginal_total": False,
        "notes": "",
    }


def fixed_summary() -> pd.DataFrame:
    return pd.read_csv(
        FIXED_ROOT / "fixed_ownership_application_summary.csv"
    ).set_index("scenario")


def build_summary_rows(
    scenario: str,
    components: dict[str, pd.DataFrame],
    legs: pd.DataFrame,
    fixed: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    private = legs["vehicle_class"].eq("private_car")
    motorcycle = legs["vehicle_class"].eq("motorcycle")
    complete = legs["marginal_cost_complete"]
    incomplete_private = private & ~complete

    overview = blank_summary_row(scenario)
    overview.update(
        {
            "summary_dimension": "scenario_overview",
            "group_value": "all_car_legs",
            "record_count": int(len(legs)),
            "private_car_count": int(private.sum()),
            "motorcycle_count": int(motorcycle.sum()),
            "complete_private_car_count": int(complete.sum()),
            "incomplete_private_car_count": int(
                incomplete_private.sum()
            ),
            "notes": (
                "Fixed ownership cost excluded; incomplete totals remain null."
            ),
        }
    )
    rows.append(overview)

    for component in COMPONENTS:
        frame = components[component]
        resolved, unresolved, out_of_scope = resolved_status_counts(
            component, frame
        )
        resolved_values = frame.loc[
            frame["cost_status"].map(
                lambda value, name=component: status_is_resolved(
                    name, value
                )
            ),
            "cost_hkd",
        ]
        row = blank_summary_row(scenario)
        row.update(
            {
                "summary_dimension": "component",
                "group_value": component,
                "cost_component": component,
                "record_count": int(len(frame)),
                "private_car_count": int(
                    frame["vehicle_class"].eq("private_car").sum()
                ),
                "motorcycle_count": int(
                    frame["vehicle_class"].eq("motorcycle").sum()
                ),
                "resolved_count": resolved,
                "unresolved_count": unresolved,
                "out_of_scope_count": out_of_scope,
                "resolved_only_total_hkd": float(
                    resolved_values.sum()
                ),
                "included_in_behavioral_marginal_total": True,
                "notes": (
                    "Component retained independently; only complete legs "
                    "enter behavioral marginal totals."
                ),
                **statistics(resolved_values),
            }
        )
        rows.append(row)
        for status, status_frame in frame.groupby(
            "cost_status", sort=True, dropna=False
        ):
            status_row = blank_summary_row(scenario)
            status_row.update(
                {
                    "summary_dimension": f"{component}_status",
                    "group_value": str(status),
                    "cost_component": component,
                    "record_count": int(len(status_frame)),
                    "private_car_count": int(
                        status_frame["vehicle_class"]
                        .eq("private_car")
                        .sum()
                    ),
                    "motorcycle_count": int(
                        status_frame["vehicle_class"]
                        .eq("motorcycle")
                        .sum()
                    ),
                    "resolved_count": int(
                        status_frame["cost_status"]
                        .map(
                            lambda value, name=component: (
                                status_is_resolved(name, value)
                            )
                        )
                        .sum()
                    ),
                    "unresolved_count": int(
                        (
                            ~status_frame["cost_status"].map(
                                lambda value, name=component: (
                                    status_is_resolved(name, value)
                                )
                            )
                            & ~status_frame["cost_status"].map(
                                status_is_out_of_scope
                            )
                        ).sum()
                    ),
                    "out_of_scope_count": int(
                        status_frame["cost_status"]
                        .map(status_is_out_of_scope)
                        .sum()
                    ),
                    "resolved_only_total_hkd": float(
                        status_frame["cost_hkd"].sum(min_count=1)
                    ),
                    "included_in_behavioral_marginal_total": (
                        status_is_resolved(component, status)
                    ),
                    "notes": "Source candidate status retained verbatim.",
                }
            )
            rows.append(status_row)

    behavioral = blank_summary_row(scenario)
    behavioral_values = legs.loc[
        complete, "behavioral_marginal_cost_hkd"
    ]
    behavioral.update(
        {
            "summary_dimension": "behavioral_complete",
            "group_value": "three_required_components_resolved",
            "record_count": int(complete.sum()),
            "private_car_count": int(complete.sum()),
            "complete_private_car_count": int(complete.sum()),
            "incomplete_private_car_count": int(
                incomplete_private.sum()
            ),
            "complete_behavioral_total_hkd": float(
                behavioral_values.sum()
            ),
            "included_in_behavioral_marginal_total": True,
            "notes": (
                "Energy plus toll plus destination parking; fixed ownership "
                "cost excluded."
            ),
            **statistics(behavioral_values),
        }
    )
    rows.append(behavioral)

    for dimension, column in (
        ("destination_activity_group", "destination_activity_group"),
        ("distance_band", "distance_band"),
    ):
        for group, group_frame in legs.groupby(
            column, sort=True, dropna=False
        ):
            group_private = group_frame["vehicle_class"].eq(
                "private_car"
            )
            group_complete = group_frame["marginal_cost_complete"]
            values = group_frame.loc[
                group_complete, "behavioral_marginal_cost_hkd"
            ]
            row = blank_summary_row(scenario)
            row.update(
                {
                    "summary_dimension": dimension,
                    "group_value": str(group),
                    "record_count": int(len(group_frame)),
                    "private_car_count": int(group_private.sum()),
                    "motorcycle_count": int(
                        group_frame["vehicle_class"]
                        .eq("motorcycle")
                        .sum()
                    ),
                    "complete_private_car_count": int(
                        group_complete.sum()
                    ),
                    "incomplete_private_car_count": int(
                        (group_private & ~group_complete).sum()
                    ),
                    "complete_behavioral_total_hkd": float(
                        values.sum()
                    ),
                    "included_in_behavioral_marginal_total": True,
                    "notes": (
                        "Statistics use complete private-car legs only."
                    ),
                    **statistics(values),
                }
            )
            rows.append(row)

    fixed_row = blank_summary_row(scenario)
    fixed_row.update(
        {
            "summary_dimension": "fixed_accounting_sidecar_reference",
            "group_value": "partial_fixed_vehicle_ownership_proxy",
            "record_count": int(fixed.loc[scenario, "unique_vehicle_days"]),
            "accounting_sidecar_total_hkd": float(
                fixed.loc[
                    scenario, "total_fixed_ownership_cost_hkd"
                ]
            ),
            "included_in_behavioral_marginal_total": False,
            "notes": (
                "Accounting sidecar only; never copied or summed into a leg."
            ),
        }
    )
    rows.append(fixed_row)
    return rows


def component_registry() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cost_component": "fuel_or_electricity",
                "cost_nature": "trip_conditional_marginal_cost",
                "behavioral_total_rule": "include_if_resolved",
                "required_for_complete_behavioral_total": True,
                "behavioral_inclusion_current_model": True,
                "eligible_for_future_scoring_pilot": True,
                "eligible_for_matsim_scoring": False,
                "incremental_if_car_leg_chosen": True,
                "record_scope": "leg_marginal_cost_component",
                "allowed_use": (
                    "offline_behavioral_marginal_cost_interface_only"
                ),
            },
            {
                "cost_component": "toll",
                "cost_nature": "trip_conditional_marginal_cost",
                "behavioral_total_rule": "include_if_resolved",
                "required_for_complete_behavioral_total": True,
                "behavioral_inclusion_current_model": True,
                "eligible_for_future_scoring_pilot": True,
                "eligible_for_matsim_scoring": False,
                "incremental_if_car_leg_chosen": True,
                "record_scope": "leg_marginal_cost_component",
                "allowed_use": (
                    "offline_behavioral_marginal_cost_interface_only"
                ),
            },
            {
                "cost_component": "destination_parking",
                "cost_nature": "trip_conditional_marginal_cost",
                "behavioral_total_rule": "include_if_resolved",
                "required_for_complete_behavioral_total": True,
                "behavioral_inclusion_current_model": True,
                "eligible_for_future_scoring_pilot": True,
                "eligible_for_matsim_scoring": False,
                "incremental_if_car_leg_chosen": True,
                "record_scope": "leg_marginal_cost_component",
                "allowed_use": (
                    "offline_behavioral_marginal_cost_interface_only"
                ),
            },
            {
                "cost_component": "fixed_vehicle_ownership_cost",
                "cost_nature": (
                    "fixed_sunk_at_daily_mode_choice_horizon"
                ),
                "behavioral_total_rule": "always_exclude",
                "required_for_complete_behavioral_total": False,
                "behavioral_inclusion_current_model": False,
                "eligible_for_future_scoring_pilot": False,
                "eligible_for_matsim_scoring": False,
                "incremental_if_car_leg_chosen": False,
                "record_scope": "vehicle_day_accounting_proxy",
                "allowed_use": (
                    "accounting_policy_and_future_long_term_ownership_"
                    "analysis_only"
                ),
            },
        ]
    )


def fixed_sidecar_reference(
    bundle_sha256: str,
    fixed: pd.DataFrame,
) -> dict[str, Any]:
    files = {
        path.relative_to(FIXED_ROOT).as_posix(): sha256_file(path)
        for path in sorted(FIXED_ROOT.rglob("*"))
        if path.is_file()
    }
    return {
        "candidate_path": FIXED_ROOT.as_posix(),
        "source_commit": SOURCE_COMMIT,
        "candidate_bundle_sha256": bundle_sha256,
        "candidate_file_sha256": files,
        "record_scope": "vehicle_day_accounting_proxy",
        "fixed_cost_proxy_name": (
            "partial_fixed_vehicle_ownership_proxy"
        ),
        "cost_nature": "fixed_sunk_at_daily_mode_choice_horizon",
        "incremental_if_car_leg_chosen": False,
        "behavioral_inclusion_current_model": False,
        "eligible_for_matsim_scoring": False,
        "excluded_from_behavioral_marginal_total": True,
        "current_model_decision_horizon": (
            "daily_travel_and_mode_choice"
        ),
        "allowed_use": (
            "accounting_policy_and_future_long_term_ownership_analysis_only"
        ),
        "owner_observed": False,
        "complete_tco": False,
        "unused_owned_vehicles_observed": False,
        "reason": (
            "fixed_cost_paid_regardless_of_daily_mode_choice_under_"
            "exogenous_vehicle_ownership"
        ),
        "scenario_accounting_totals_hkd": {
            scenario: float(
                fixed.loc[
                    scenario, "total_fixed_ownership_cost_hkd"
                ]
            )
            for scenario in SCENARIOS
        },
        "copied_to_leg_component_table": False,
        "joined_to_first_or_last_vehicle_leg": False,
    }


def legal_zero_audit(
    component: str,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    zero = frame.loc[frame["cost_hkd"].eq(0)].copy()
    allowed = {
        "fuel_or_electricity": {
            "resolved_zero_distance_energy_zero"
        },
        "toll": {"confirmed_no_charge"},
        "destination_parking": {
            "resolved_home_marginal_zero_fixed_separate",
            "resolved_work_subscription_assumed_prepaid",
        },
    }[component]
    counts = {
        str(key): int(value)
        for key, value in zero["cost_status"].value_counts().items()
    }
    return {
        "zero_cost_count": int(len(zero)),
        "zero_status_counts": counts,
        "allowed_zero_statuses": sorted(allowed),
        "only_allowed_statuses_have_zero": set(counts).issubset(allowed),
    }


def validate_outputs(
    all_components: dict[str, dict[str, pd.DataFrame]],
    leg_summaries: dict[str, pd.DataFrame],
    input_diagnostics: dict[str, Any],
    canonical_diagnostics: dict[str, Any],
    candidate_validation: dict[str, Any],
    registry: pd.DataFrame,
) -> dict[str, Any]:
    scenario_results: dict[str, Any] = {}
    hard_checks: dict[str, bool] = {}
    for scenario in SCENARIOS:
        components = all_components[scenario]
        long = pd.concat(
            [components[name] for name in COMPONENTS],
            ignore_index=True,
        )
        legs = leg_summaries[scenario]
        private = legs["vehicle_class"].eq("private_car")
        motorcycle = legs["vehicle_class"].eq("motorcycle")
        complete = legs["marginal_cost_complete"]
        incomplete_private = private & ~complete
        parking_unresolved = components["destination_parking"][
            "cost_status"
        ].astype(str).str.startswith("unresolved_")
        unresolved_zero_count = 0
        for component in COMPONENTS:
            frame = components[component]
            unresolved_or_out = ~frame["cost_status"].map(
                lambda value, name=component: status_is_resolved(
                    name, value
                )
            )
            unresolved_zero_count += int(
                frame.loc[
                    unresolved_or_out, "cost_hkd"
                ].eq(0).sum()
            )
        sum_error = (
            legs.loc[complete, "behavioral_marginal_cost_hkd"]
            - (
                legs.loc[complete, "fuel_or_electricity_hkd"]
                + legs.loc[complete, "toll_hkd"]
                + legs.loc[complete, "destination_parking_hkd"]
            )
        ).abs().max()
        zero_audit = {
            component: legal_zero_audit(
                component, components[component]
            )
            for component in COMPONENTS
        }
        scenario_result = {
            "component_row_count": int(len(long)),
            "component_key_unique": bool(
                ~long.duplicated(
                    KEY_COLUMNS + ["scenario", "cost_component"]
                ).any()
            ),
            "component_counts": {
                component: int(
                    long["cost_component"].eq(component).sum()
                )
                for component in COMPONENTS
            },
            "leg_summary_row_count": int(len(legs)),
            "leg_summary_key_unique": bool(
                ~legs.duplicated(KEY_COLUMNS + ["scenario"]).any()
            ),
            "private_car_legs": int(private.sum()),
            "motorcycle_out_of_scope": int(motorcycle.sum()),
            "complete_private_car_legs": int(complete.sum()),
            "incomplete_private_car_legs": int(
                incomplete_private.sum()
            ),
            "parking_unresolved_private_car_legs": int(
                (
                    parking_unresolved
                    & components["destination_parking"][
                        "vehicle_class"
                    ].eq("private_car")
                ).sum()
            ),
            "incomplete_behavioral_total_null": bool(
                legs.loc[
                    incomplete_private,
                    "behavioral_marginal_cost_hkd",
                ].isna().all()
            ),
            "motorcycle_all_component_costs_null": bool(
                long.loc[
                    long["vehicle_class"].eq("motorcycle"),
                    "cost_hkd",
                ].isna().all()
            ),
            "motorcycle_behavioral_total_null": bool(
                legs.loc[
                    motorcycle, "behavioral_marginal_cost_hkd"
                ].isna().all()
            ),
            "unresolved_or_out_of_scope_zero_count": (
                unresolved_zero_count
            ),
            "complete_leg_formula_max_abs_error_hkd": float(
                sum_error if pd.notna(sum_error) else 0.0
            ),
            "component_resolved_only_totals_hkd": {
                component: float(
                    components[component]["cost_hkd"].sum(
                        skipna=True
                    )
                )
                for component in COMPONENTS
            },
            "complete_behavioral_marginal_total_hkd": float(
                legs.loc[
                    complete, "behavioral_marginal_cost_hkd"
                ].sum()
            ),
            "complete_behavioral_statistics_hkd": statistics(
                legs.loc[
                    complete, "behavioral_marginal_cost_hkd"
                ]
            ),
            "legal_zero_audit": zero_audit,
            "fixed_component_rows_in_leg_long_table": int(
                long["cost_component"]
                .eq("fixed_vehicle_ownership_cost")
                .sum()
            ),
            "fixed_cost_included_true_count": int(
                legs["fixed_vehicle_ownership_cost_included"].sum()
            ),
            "fixed_cost_non_null_count": int(
                legs["fixed_vehicle_ownership_cost_hkd"].notna().sum()
            ),
            "scoring_adoption_approved_true_count": int(
                legs["scoring_adoption_approved"].sum()
            ),
        }
        scenario_results[scenario] = scenario_result
        hard_checks[f"{scenario}_component_rows_203154"] = (
            scenario_result["component_row_count"] == 203_154
        )
        hard_checks[f"{scenario}_summary_rows_67718"] = (
            scenario_result["leg_summary_row_count"] == 67_718
        )
        hard_checks[f"{scenario}_component_keys_unique"] = (
            scenario_result["component_key_unique"]
        )
        hard_checks[f"{scenario}_summary_keys_unique"] = (
            scenario_result["leg_summary_key_unique"]
        )
        hard_checks[f"{scenario}_complete_private_63954"] = (
            scenario_result["complete_private_car_legs"] == 63_954
        )
        hard_checks[f"{scenario}_incomplete_private_835"] = (
            scenario_result["incomplete_private_car_legs"] == 835
        )
        hard_checks[f"{scenario}_motorcycles_2929"] = (
            scenario_result["motorcycle_out_of_scope"] == 2_929
        )
        hard_checks[f"{scenario}_unresolved_not_zero"] = (
            scenario_result["unresolved_or_out_of_scope_zero_count"]
            == 0
        )
        hard_checks[f"{scenario}_incomplete_total_null"] = (
            scenario_result["incomplete_behavioral_total_null"]
        )
        hard_checks[f"{scenario}_motorcycle_components_null"] = (
            scenario_result["motorcycle_all_component_costs_null"]
        )
        hard_checks[f"{scenario}_motorcycle_total_null"] = (
            scenario_result["motorcycle_behavioral_total_null"]
        )
        hard_checks[f"{scenario}_formula_exact"] = (
            scenario_result[
                "complete_leg_formula_max_abs_error_hkd"
            ]
            <= FLOAT_TOLERANCE
        )
        hard_checks[f"{scenario}_fixed_absent_from_legs"] = (
            scenario_result["fixed_component_rows_in_leg_long_table"]
            == 0
            and scenario_result["fixed_cost_included_true_count"] == 0
            and scenario_result["fixed_cost_non_null_count"] == 0
        )
        hard_checks[f"{scenario}_legal_zero_statuses"] = all(
            value["only_allowed_statuses_have_zero"]
            for value in zero_audit.values()
        )

    hard_checks["all_input_candidate_validations_publishable"] = all(
        value["publishable_candidate"] and not value["blocked"]
        for value in candidate_validation.values()
    )
    hard_checks["canonical_identity_contract_valid"] = all(
        bool(value)
        for key, value in canonical_diagnostics.items()
        if key.endswith("_equal")
        or key.endswith("_private_vehicles")
    )
    hard_checks["all_component_key_sets_identical"] = all(
        details["keys_match_canonical"]
        for scenario in input_diagnostics.values()
        for details in scenario.values()
    )
    hard_checks["all_vehicle_identity_checks_valid"] = all(
        details[
            "vehicle_identity_matches_canonical_when_present"
        ]
        for scenario in input_diagnostics.values()
        for details in scenario.values()
    )
    hard_checks["three_scenarios_component_rows_609462"] = (
        sum(
            result["component_row_count"]
            for result in scenario_results.values()
        )
        == 609_462
    )
    fixed_registry = registry.loc[
        registry["cost_component"].eq(
            "fixed_vehicle_ownership_cost"
        )
    ].iloc[0]
    hard_checks["fixed_registry_behavioral_exclusion_valid"] = bool(
        fixed_registry["behavioral_total_rule"] == "always_exclude"
        and not fixed_registry["behavioral_inclusion_current_model"]
        and not fixed_registry["eligible_for_future_scoring_pilot"]
        and not fixed_registry["eligible_for_matsim_scoring"]
        and not fixed_registry["incremental_if_car_leg_chosen"]
    )
    publishable = all(hard_checks.values())
    return {
        "audit": (
            "Hong Kong private-car unified offline marginal-cost "
            "interface and behavioral-boundary audit v1"
        ),
        "source_commit": SOURCE_COMMIT,
        "candidate_build_date": CANDIDATE_BUILD_DATE,
        "candidate_build_date_semantics": (
            "interface_build_date_not_component_rate_effective_date"
        ),
        "publishable_candidate": publishable,
        "blocked": not publishable,
        "candidate_output_only": True,
        "matsim_scoring_modified": False,
        "scoring_adoption_approved": False,
        "joint_mode_choice_calibration_approved": False,
        "fixed_vehicle_ownership_behavioral_inclusion": False,
        "current_model_decision_horizon": (
            "daily_travel_and_mode_choice_under_exogenous_vehicle_ownership"
        ),
        "canonical_identity": canonical_diagnostics,
        "source_candidate_validations": candidate_validation,
        "input_join_diagnostics": input_diagnostics,
        "scenario_outputs": scenario_results,
        "all_scenarios_component_row_count": int(
            sum(
                result["component_row_count"]
                for result in scenario_results.values()
            )
        ),
        "fixed_ownership_boundary": {
            "cost_nature": (
                "fixed_sunk_at_daily_mode_choice_horizon"
            ),
            "incremental_if_car_leg_chosen": False,
            "behavioral_inclusion_current_model": False,
            "eligible_for_matsim_scoring": False,
            "excluded_from_behavioral_marginal_total": True,
            "allowed_use": (
                "accounting_policy_and_future_long_term_ownership_"
                "analysis_only"
            ),
        },
        "hard_checks": hard_checks,
    }


def required_repairs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "repair_id": "UNIFIED-R01",
                "severity": "low",
                "blocking": False,
                "component": "toll_vehicle_identity",
                "finding": (
                    "The toll leg candidate does not embed vehicle_ref_id "
                    "or vehicle_class."
                ),
                "required_change": (
                    "Continue strict one-to-one enrichment from canonical "
                    "identity unless a future toll candidate adds the fields."
                ),
            },
            {
                "repair_id": "UNIFIED-R02",
                "severity": "medium",
                "blocking": False,
                "component": "destination_parking",
                "finding": (
                    "835 private-car legs have unresolved destination "
                    "parking and therefore no complete marginal total."
                ),
                "required_change": (
                    "Repair vehicle-chain, destination-zone, or terminal "
                    "duration evidence before treating those totals as complete."
                ),
            },
            {
                "repair_id": "UNIFIED-R03",
                "severity": "medium",
                "blocking": False,
                "component": "fixed_ownership_scope",
                "finding": (
                    "The fixed sidecar covers used vehicles only; unused "
                    "owned vehicles are not observed."
                ),
                "required_change": (
                    "Keep the sidecar out of daily mode-choice behavior and "
                    "use it only for accounting or future ownership analysis."
                ),
            },
            {
                "repair_id": "UNIFIED-R04",
                "severity": "high",
                "blocking": False,
                "component": "scoring_adoption",
                "finding": (
                    "This publishable offline interface has no approval for "
                    "MATSim scoring or joint mode-choice calibration."
                ),
                "required_change": (
                    "Require a separate approved behavioral design, monetary "
                    "utility calibration, implementation, and validation."
                ),
            },
        ]
    )


def main() -> None:
    args = parse_args()
    input_root = args.input_project_root.resolve()
    canonical = canonical_paths(input_root)
    required_local = [
        FEASIBILITY_PATH,
        SOURCE_MANIFEST_PATH,
        *[
            component_path(component, scenario)
            for scenario in SCENARIOS
            for component in COMPONENTS
        ],
        *[
            root
            for root in candidate_roots().values()
        ],
    ]
    missing = [str(path) for path in required_local if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing unified-interface inputs: {missing}"
        )

    protected = protected_paths(args.output_dir)
    protected_before = hash_map(protected)
    canonical_before = hash_map(canonical)
    bundles_before = candidate_bundles()

    candidate_validation = assert_candidate_validation()
    identity, canonical_diagnostics = normalized_identity(canonical)
    snapshot_hashes = source_snapshot_hashes()
    all_components: dict[str, dict[str, pd.DataFrame]] = {}
    input_diagnostics: dict[str, Any] = {}
    leg_summaries: dict[str, pd.DataFrame] = {}
    summary_rows: list[dict[str, Any]] = []
    fixed = fixed_summary()

    for scenario in SCENARIOS:
        all_components[scenario] = {}
        input_diagnostics[scenario] = {}
        for component in COMPONENTS:
            frame, diagnostics = read_component(
                component,
                scenario,
                identity,
                snapshot_hashes[component],
            )
            all_components[scenario][component] = frame
            input_diagnostics[scenario][component] = diagnostics
        leg_summaries[scenario] = build_leg_summary(
            all_components[scenario], scenario
        )
        summary_rows.extend(
            build_summary_rows(
                scenario,
                all_components[scenario],
                leg_summaries[scenario],
                fixed,
            )
        )

    registry = component_registry()
    validation = validate_outputs(
        all_components,
        leg_summaries,
        input_diagnostics,
        canonical_diagnostics,
        candidate_validation,
        registry,
    )
    fixed_reference = fixed_sidecar_reference(
        bundles_before["fixed_ownership_application_v1"],
        fixed,
    )
    repairs = required_repairs()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        component_long = pd.concat(
            [
                all_components[scenario][component]
                for component in COMPONENTS
            ],
            ignore_index=True,
        )
        order = {
            component: index
            for index, component in enumerate(COMPONENTS)
        }
        component_long["_component_order"] = component_long[
            "cost_component"
        ].map(order)
        component_long = component_long.sort_values(
            KEY_COLUMNS + ["_component_order"],
            kind="mergesort",
        ).drop(columns="_component_order")
        component_long.to_parquet(
            args.output_dir
            / f"car_leg_marginal_cost_components_{scenario}.parquet",
            index=False,
        )
        leg_summaries[scenario].to_parquet(
            args.output_dir
            / f"car_leg_marginal_cost_summary_{scenario}.parquet",
            index=False,
        )
    registry.to_csv(
        args.output_dir / "marginal_cost_component_registry.csv",
        index=False,
        encoding="utf-8",
    )
    write_json(
        args.output_dir
        / "fixed_ownership_accounting_sidecar_reference.json",
        fixed_reference,
    )
    pd.DataFrame(summary_rows).to_csv(
        args.output_dir / "unified_marginal_cost_summary.csv",
        index=False,
        encoding="utf-8",
    )
    repairs.to_csv(
        args.output_dir / "unified_marginal_cost_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )

    protected_after = hash_map(protected)
    canonical_after = hash_map(canonical)
    bundles_after = candidate_bundles()
    protection = {
        "canonical_inputs_unchanged": (
            canonical_before == canonical_after
        ),
        "all_existing_car_cost_files_unchanged": (
            protected_before == protected_after
        ),
        "candidate_bundles_unchanged": (
            bundles_before == bundles_after
        ),
        "energy_application_v1_unchanged": (
            bundles_before["energy_application_v1"]
            == bundles_after["energy_application_v1"]
        ),
        "toll_network_mapping_v1_unchanged": (
            bundles_before["toll_network_mapping_v1"]
            == bundles_after["toll_network_mapping_v1"]
        ),
        "toll_rate_application_v1_unchanged": (
            bundles_before["toll_rate_application_v1"]
            == bundles_after["toll_rate_application_v1"]
        ),
        "parking_event_application_v1_unchanged": (
            bundles_before["parking_event_application_v1"]
            == bundles_after["parking_event_application_v1"]
        ),
        "fixed_ownership_application_v1_unchanged": (
            bundles_before["fixed_ownership_application_v1"]
            == bundles_after["fixed_ownership_application_v1"]
        ),
        "old_unified_car_cost_files_unchanged": all(
            protected_before[key] == protected_after[key]
            for key in protected_before
            if (
                "/car_leg_cost_estimates_" in key
                or key.endswith("/car_cost_model_validation.json")
            )
        ),
        "matsim_plans_config_network_facilities_vehicles_unchanged": (
            canonical_before == canonical_after
        ),
        "pt_core_files_unchanged": all(
            canonical_before[key] == canonical_after[key]
            for key in (
                "network",
                "transit_schedule",
                "transit_vehicles",
            )
        ),
        "taxi_files_read_or_written": False,
    }
    protection["all_protected_sha256_unchanged"] = bool(
        protection["canonical_inputs_unchanged"]
        and protection["all_existing_car_cost_files_unchanged"]
        and protection["candidate_bundles_unchanged"]
    )
    validation["protected_inputs"] = protection
    validation["required_repairs"] = {
        "row_count": int(len(repairs)),
        "blocking_count": int(repairs["blocking"].sum()),
    }
    if not protection["all_protected_sha256_unchanged"]:
        validation["publishable_candidate"] = False
        validation["blocked"] = True

    hashes = {
        "input_root_role": (
            "canonical_project_read_only_large_inputs;"
            "absolute_root_omitted"
        ),
        "source_commit": SOURCE_COMMIT,
        "canonical_role_paths": {
            key: path.relative_to(input_root).as_posix()
            for key, path in canonical.items()
        },
        "canonical_hashes_before": canonical_before,
        "canonical_hashes_after": canonical_after,
        "candidate_bundle_sha256_before": bundles_before,
        "candidate_bundle_sha256_after": bundles_after,
        "component_candidate_file_sha256": {
            scenario: {
                component: sha256_file(
                    component_path(component, scenario)
                )
                for component in COMPONENTS
            }
            for scenario in SCENARIOS
        },
        "source_snapshot_sha256_by_component": snapshot_hashes,
        "existing_car_cost_hashes_before": protected_before,
        "existing_car_cost_hashes_after": protected_after,
        "all_protected_sha256_unchanged": protection[
            "all_protected_sha256_unchanged"
        ],
    }
    write_json(
        args.output_dir / "unified_marginal_cost_validation.json",
        validation,
    )
    write_json(
        args.output_dir / "unified_marginal_cost_input_hashes.json",
        hashes,
    )
    if validation["blocked"]:
        raise RuntimeError(
            "Unified marginal-cost interface failed a hard validation"
        )
    print(
        json.dumps(
            {
                "output_dir": args.output_dir.as_posix(),
                "publishable_candidate": True,
                "blocked": False,
                "all_scenarios_component_rows": validation[
                    "all_scenarios_component_row_count"
                ],
                "scenario_results": {
                    scenario: {
                        "component_rows": validation[
                            "scenario_outputs"
                        ][scenario]["component_row_count"],
                        "summary_rows": validation[
                            "scenario_outputs"
                        ][scenario]["leg_summary_row_count"],
                        "complete_private_car_legs": validation[
                            "scenario_outputs"
                        ][scenario]["complete_private_car_legs"],
                        "incomplete_private_car_legs": validation[
                            "scenario_outputs"
                        ][scenario]["incomplete_private_car_legs"],
                        "behavioral_total_hkd": validation[
                            "scenario_outputs"
                        ][scenario][
                            "complete_behavioral_marginal_total_hkd"
                        ],
                    }
                    for scenario in SCENARIOS
                },
                "fixed_vehicle_ownership_behavioral_inclusion": False,
                "scoring_adoption_approved": False,
                "all_protected_sha256_unchanged": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
