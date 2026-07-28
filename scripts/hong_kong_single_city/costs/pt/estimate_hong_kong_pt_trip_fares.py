"""Build a chargeability audit for every Hong Kong production PT main leg.

The production routed plans serialize all current PT main legs as generic
routes. They do not contain the actual transit mode, line, route, direction,
boarding stop, alighting stop, or transfer chain needed to select an official
fare rule. This script therefore retains one audit row per PT trip with
``cost_hkd`` null. It does not estimate, average, clip, or impute fares.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
MISSING_ITINERARY_FIELDS = (
    "actual_transport_mode",
    "actual_line_id",
    "actual_route_id",
    "actual_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "transfer_chain",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit every production PT main leg and leave cost_hkd null when "
            "the serialized itinerary is not uniquely chargeable."
        )
    )
    parser.add_argument("--source-project-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def choose_source_root(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    local = repository_root()
    manifest = (
        local
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/"
        "agent_trip_manifest_v2.parquet"
    )
    return local if manifest.exists() else CANONICAL_SOURCE_ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def selected_plan(person: ET.Element) -> ET.Element:
    plans = [element for element in person if tag_name(element) == "plan"]
    selected = [
        plan
        for plan in plans
        if plan.attrib.get("selected", "yes").lower() in {"yes", "true", "1"}
    ]
    if selected:
        return selected[0]
    if plans:
        return plans[0]
    raise ValueError(f"Person {person.attrib.get('id')} has no plan")


def read_serialized_pt_legs(plans_path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with gzip.open(plans_path, "rb") as handle:
        for _, person in ET.iterparse(handle, events=("end",)):
            if tag_name(person) != "person":
                continue
            person_id = person.attrib["id"]
            pt_ordinal = 0
            plan = selected_plan(person)
            for element in plan:
                if tag_name(element) != "leg" or element.attrib.get("mode") != "pt":
                    continue
                route = next(
                    (child for child in element if tag_name(child) == "route"),
                    None,
                )
                route_attributes = dict(route.attrib) if route is not None else {}
                route_text = (
                    (route.text or "").strip() if route is not None else ""
                )
                rows.append(
                    {
                        "person_id": person_id,
                        "pt_ordinal": pt_ordinal,
                        "serialized_leg_mode": "pt",
                        "serialized_route_type": route_attributes.get("type", ""),
                        "serialized_route_attribute_names": ";".join(
                            sorted(route_attributes)
                        ),
                        "serialized_route_has_text": bool(route_text),
                        "serialized_start_link_id": route_attributes.get(
                            "start_link", ""
                        ),
                        "serialized_end_link_id": route_attributes.get(
                            "end_link", ""
                        ),
                        "serialized_route_distance_m": pd.to_numeric(
                            route_attributes.get("distance", ""), errors="coerce"
                        ),
                        "serialized_route_travel_time": route_attributes.get(
                            "trav_time", ""
                        ),
                        "actual_transport_mode": pd.NA,
                        "actual_line_id": pd.NA,
                        "actual_route_id": pd.NA,
                        "actual_direction": pd.NA,
                        "boarding_stop_id": pd.NA,
                        "alighting_stop_id": pd.NA,
                        "transfer_chain": pd.NA,
                    }
                )
                pt_ordinal += 1
            person.clear()
    return pd.DataFrame(rows)


def write_sha256s(output_dir: Path) -> None:
    paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in paths) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    source_root = choose_source_root(args.source_project_root)
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else repository_root() / "data/transport_costs/hongkong/pt_fare_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    demand_dir = (
        source_root
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
    )
    manifest_path = demand_dir / "agent_trip_manifest_v2.parquet"
    plans_path = demand_dir / "plans_routed_5pct_v2.xml.gz"
    for path in (manifest_path, plans_path):
        if not path.exists():
            raise FileNotFoundError(path)

    print("Reading PT manifest and serialized production PT legs...", flush=True)
    manifest = pd.read_parquet(manifest_path)
    trips = manifest[manifest["mode"].eq("pt")].copy()
    trips["pt_ordinal"] = trips.groupby("person_id", sort=False).cumcount()
    serialized = read_serialized_pt_legs(plans_path)
    output = trips.merge(
        serialized,
        on=["person_id", "pt_ordinal"],
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not output["_merge"].eq("both").all():
        counts = output["_merge"].value_counts().to_dict()
        raise ValueError(f"Manifest/plan PT-leg mismatch: {counts}")
    output = output.drop(columns=["_merge", "pt_ordinal"])

    generic = output["serialized_route_type"].eq("generic")
    output["cost_component"] = "pt_fare_chargeability_audit"
    output["cost_hkd"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="Float64"), index=output.index
    )
    output["cost_source"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="string"), index=output.index
    )
    output["cost_effective_date"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="string"), index=output.index
    )
    output["cost_quality"] = "U"
    output["mapping_status"] = "unresolved"
    output["unresolved_reason"] = generic.map(
        {
            True: (
                "generic_pt_leg_missing_actual_mode_line_route_boarding_"
                "alighting_transfer_chain"
            ),
            False: "serialized_pt_route_not_sufficient_for_unique_fare_rule",
        }
    )
    output["required_missing_fields"] = ";".join(MISSING_ITINERARY_FIELDS)
    output["source_record_id"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="string"), index=output.index
    )
    output["fare_scope"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="string"), index=output.index
    )
    output["transfer_concession_hkd"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="Float64"), index=output.index
    )
    output["transfer_concession_status"] = (
        "not_modelled_no_serialized_transfer_chain_or_eligibility"
    )
    output["transfer_concession_source"] = pd.Series(
        pd.array([pd.NA] * len(output), dtype="string"), index=output.index
    )
    output["fare_passenger_type"] = "adult_reference_not_applied"
    output["fare_payment_medium"] = "Octopus_reference_not_applied"
    output["estimation_method"] = "audit_only_no_fare_estimation"

    required_columns = [
        "person_id",
        "leg_sequence",
        "mode",
        "cost_component",
        "cost_hkd",
        "cost_source",
        "cost_effective_date",
        "cost_quality",
        "mapping_status",
        "unresolved_reason",
        "required_missing_fields",
    ]
    additional_columns = [
        "population_group",
        "role",
        "origin_type",
        "destination_type",
        "origin_facility_id",
        "destination_facility_id",
        "departure_time_s",
        "is_discretionary",
        "serialized_leg_mode",
        "serialized_route_type",
        "serialized_route_attribute_names",
        "serialized_route_has_text",
        "serialized_start_link_id",
        "serialized_end_link_id",
        "serialized_route_distance_m",
        "serialized_route_travel_time",
        "actual_transport_mode",
        "actual_line_id",
        "actual_route_id",
        "actual_direction",
        "boarding_stop_id",
        "alighting_stop_id",
        "transfer_chain",
        "source_record_id",
        "fare_scope",
        "transfer_concession_hkd",
        "transfer_concession_status",
        "transfer_concession_source",
        "fare_passenger_type",
        "fare_payment_medium",
        "estimation_method",
    ]
    output = output[required_columns + additional_columns].sort_values(
        ["person_id", "leg_sequence"]
    )
    audit_path = output_dir / "pt_passenger_trip_fare_audit.parquet"
    output.to_parquet(audit_path, index=False, compression="zstd")
    output.head(1000).to_csv(
        output_dir / "pt_passenger_trip_fare_audit_sample.csv",
        index=False,
        encoding="utf-8",
    )

    route_type_counts = Counter(output["serialized_route_type"].fillna(""))
    route_attribute_counts = Counter(
        output["serialized_route_attribute_names"].fillna("")
    )
    field_audit = {
        "input_pt_passenger_trips": int(len(trips)),
        "serialized_pt_legs": int(len(serialized)),
        "serialized_leg_modes": {
            str(key): int(value)
            for key, value in output["serialized_leg_mode"].value_counts().items()
        },
        "serialized_route_types": {
            str(key): int(value) for key, value in route_type_counts.items()
        },
        "serialized_route_attribute_sets": {
            str(key): int(value) for key, value in route_attribute_counts.items()
        },
        "serialized_routes_with_text": int(
            output["serialized_route_has_text"].sum()
        ),
        "actual_transport_mode_non_null": int(
            output["actual_transport_mode"].notna().sum()
        ),
        "actual_line_id_non_null": int(output["actual_line_id"].notna().sum()),
        "actual_route_id_non_null": int(output["actual_route_id"].notna().sum()),
        "boarding_stop_id_non_null": int(
            output["boarding_stop_id"].notna().sum()
        ),
        "alighting_stop_id_non_null": int(
            output["alighting_stop_id"].notna().sum()
        ),
        "transfer_chain_non_null": int(output["transfer_chain"].notna().sum()),
    }
    (output_dir / "production_pt_leg_field_audit.json").write_text(
        json.dumps(field_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    build_audit = {
        "model": "Hong Kong offline public transport fare model v1",
        "model_role": "trip_chargeability_audit",
        "input_pt_passenger_trips": int(len(trips)),
        "output_audit_rows": int(len(output)),
        "unique_persons": int(output["person_id"].nunique()),
        "duplicate_person_leg_keys": int(
            output.duplicated(["person_id", "leg_sequence"]).sum()
        ),
        "non_null_cost_hkd_rows": int(output["cost_hkd"].notna().sum()),
        "unresolved_rows": int(output["mapping_status"].eq("unresolved").sum()),
        "unresolved_reason_counts": {
            str(key): int(value)
            for key, value in output["unresolved_reason"].value_counts().items()
        },
        "cross_mode_fare_aggregation_present": False,
        "distance_endpoint_clipping_present": False,
        "transfer_concession_non_null_rows": int(
            output["transfer_concession_hkd"].notna().sum()
        ),
        "input_sha256": {
            "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/"
            "agent_trip_manifest_v2.parquet": sha256(manifest_path),
            "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/"
            "plans_routed_5pct_v2.xml.gz": sha256(plans_path),
        },
    }
    if (
        build_audit["output_audit_rows"] != build_audit["input_pt_passenger_trips"]
        or build_audit["duplicate_person_leg_keys"] != 0
        or build_audit["non_null_cost_hkd_rows"] != 0
    ):
        raise AssertionError(json.dumps(build_audit, indent=2))
    (output_dir / "pt_trip_fare_build_audit.json").write_text(
        json.dumps(build_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary_path = output_dir / "pt_fare_model_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["trip_audit"] = {
        "total_pt_trips": int(len(output)),
        "priced_trips": 0,
        "unresolved_trips": int(len(output)),
        "cost_policy": "null_when_unique_chargeable_itinerary_is_absent",
        "withdrawn_method": (
            "cross_mode_distance_bin_median_from_commit_c7be4a_withdrawn"
        ),
        "cross_mode_fare_aggregation_present": False,
        "distance_endpoint_clipping_present": False,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    legacy_outputs = [
        output_dir / "pt_passenger_trip_fare_estimates.parquet",
        output_dir / "pt_passenger_trip_fare_estimates_sample.csv",
        output_dir / "pt_trip_fare_validation.json",
    ]
    for legacy_path in legacy_outputs:
        if legacy_path.exists():
            legacy_path.unlink()
    write_sha256s(output_dir)
    print(json.dumps(build_audit, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
