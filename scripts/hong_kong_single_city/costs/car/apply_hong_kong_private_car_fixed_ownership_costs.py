#!/usr/bin/env python3
"""Build an audited Hong Kong private-car fixed-ownership candidate.

The candidate contains one partial fixed vehicle-ownership proxy per used
private car per model day and scenario. It never attaches fixed cost to a
normal leg and does not modify MATSim inputs, scoring, or existing car-cost
outputs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

import fitz
from lxml import etree
import pandas as pd


CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
DEFAULT_OUTPUT = CAR_COST_ROOT / "fixed_ownership_application_v1"
SOURCE_MANIFEST_PATH = CAR_COST_ROOT / "car_cost_source_manifest.json"
FEASIBILITY_PATH = (
    CAR_COST_ROOT
    / "input_feasibility/car_leg_input_feasibility.parquet"
)
OLD_ENERGY_PARAMETERS_PATH = (
    CAR_COST_ROOT / "car_energy_cost_parameters.csv"
)
ENERGY_PARAMETERS_PATH = (
    CAR_COST_ROOT
    / "energy_application_v1/energy_parameters_repository_relative.csv"
)
SOURCE_COMMIT = "b6264a366eaab5be9bc0b470db991ee49785317f"
CANDIDATE_REFERENCE_DATE = "2026-07-29"
SCENARIOS = ("low", "base", "high")
ALLOCATION_DAYS = 365.0
FLOAT_TOLERANCE = 1e-9
PROXY_NAME = "partial_fixed_vehicle_ownership_proxy"
RECORD_SCOPE = "vehicle_day_fixed_cost_not_leg"
FLEET_PROXY = "representative_hk_licensed_private_car_fleet_average_proxy"
EXCLUSIONS = "|".join(
    [
        "depreciation",
        "vehicle_purchase_price",
        "financing_interest",
        "insurance",
        "maintenance_repair",
        "tyres",
        "inspection",
        "work_parking_subscription",
        "destination_temporary_parking",
        "fuel_or_electricity",
        "toll",
    ]
)

SOURCE_FILES = {
    "licence": (
        CAR_COST_ROOT
        / "source_snapshots/td_vehicle_licence_fees_2026.pdf"
    ),
    "housing_parking": (
        CAR_COST_ROOT
        / "source_snapshots/housing_authority_carpark_fees_2026.pdf"
    ),
    "government_parking_schedule": (
        CAR_COST_ROOT
        / "source_snapshots/td_parking_fees_2026.pdf"
    ),
    "government_parking_html": (
        CAR_COST_ROOT
        / "source_snapshots/td_government_car_parks.html"
    ),
    "fleet": (
        CAR_COST_ROOT
        / "source_snapshots/td_vehicle_fuel_type_2025_12.xls"
    ),
}

SOURCE_IDS = {
    "licence": "td_vehicle_licence_fees_2026",
    "housing_parking": "housing_authority_carpark_fees_2026",
    "government_parking_schedule": "td_parking_fees_2026",
    "government_parking_html": "td_government_car_parks",
    "fleet": "td_vehicle_fuel_type_2025_12",
}

OUTPUT_COLUMNS = [
    "person_id",
    "person_id_semantics",
    "household_id",
    "vehicle_ref_id",
    "vehicle_day_id",
    "leg_sequence",
    "mode",
    "vehicle_class",
    "scenario",
    "cost_component",
    "fixed_cost_proxy_name",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_effective_date_status",
    "cost_quality",
    "record_scope",
    "owner_observed",
    "vehicle_powertrain",
    "individual_engine_displacement_observed",
    "individual_rated_power_observed",
    "combustion_proxy_share",
    "electric_share",
    "combustion_annual_licence_hkd",
    "electric_annual_licence_hkd",
    "annual_licence_proxy_hkd",
    "daily_licence_proxy_hkd",
    "residential_monthly_parking_proxy_hkd",
    "daily_residential_parking_proxy_hkd",
    "allocation_days_per_year",
    "allocation_semantics",
    "vehicle_licence_effective_date",
    "residential_parking_effective_date",
    "candidate_reference_date",
    "candidate_reference_date_semantics",
    "exclusions",
    "assumption_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root containing large read-only inputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    return parser.parse_args()


def normalized_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
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
    result = {
        "plans_routed": demand / "plans_routed_5pct_v2.xml.gz",
        "private_vehicles": demand / "privateVehicles_5pct.xml.gz",
        "trip_manifest": demand / "agent_trip_manifest_v2.parquet",
        "synthetic_households": (
            input_root
            / "data/matsim_agents/hongkong/"
            "synthetic_households_tcs2022/synthetic_households.parquet"
        ),
    }
    missing = [key for key, path in result.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical fixed-ownership inputs: {missing}"
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


def load_source_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(
        SOURCE_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    records = {
        str(row["source_id"]): row for row in manifest["sources"]
    }
    for role, source_id in SOURCE_IDS.items():
        if source_id not in records:
            raise RuntimeError(
                f"Source manifest lacks required source {source_id}"
            )
        record = records[source_id]
        expected_path = CAR_COST_ROOT / str(record["source_file"])
        if expected_path != SOURCE_FILES[role]:
            raise RuntimeError(
                f"Source path mismatch for {source_id}: {expected_path}"
            )
        actual_hash = sha256_file(expected_path)
        if actual_hash != str(record["file_sha256"]):
            raise RuntimeError(
                f"Source snapshot hash mismatch for {source_id}"
            )
        if expected_path.stat().st_size != int(
            record["file_size_bytes"]
        ):
            raise RuntimeError(
                f"Source snapshot size mismatch for {source_id}"
            )
    return manifest, records


def repository_source_path(record: dict[str, Any]) -> str:
    return (
        CAR_COST_ROOT / str(record["source_file"])
    ).as_posix()


def pdf_page_text(path: Path, page_number: int) -> str:
    with fitz.open(path) as document:
        if not 1 <= page_number <= len(document):
            raise RuntimeError(
                f"PDF page {page_number} absent from {path}"
            )
        return document[page_number - 1].get_text("text")


def integer_amount(value: str) -> float:
    return float(value.replace(",", ""))


def extract_annual_fee(block: str, category: str) -> float:
    match = re.search(
        category + r"\s+([0-9,]+)\s+([0-9,]+)",
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        raise RuntimeError(
            f"Annual licence fee category not found: {category}"
        )
    return integer_amount(match.group(1))


def extract_licence_parameters() -> dict[str, Any]:
    text = pdf_page_text(SOURCE_FILES["licence"], 2)
    petrol_match = re.search(
        r"Private Car \(Petrol\)(.*?)Private Car \(Electric\)",
        text,
        flags=re.DOTALL,
    )
    electric_match = re.search(
        r"Private Car \(Electric\)(.*?)Private Car \(Light Diesel\)",
        text,
        flags=re.DOTALL,
    )
    if petrol_match is None or electric_match is None:
        raise RuntimeError(
            "Petrol/electric licence tables not found on TD341 page 2"
        )
    petrol = petrol_match.group(1)
    electric = electric_match.group(1)
    extracted = {
        "low": {
            "combustion": extract_annual_fee(
                petrol,
                r"not exceeding 1,500cc\.",
            ),
            "electric": extract_annual_fee(
                electric,
                r"not exceeding 75kW",
            ),
            "combustion_category": (
                "Private Car (Petrol), cylinder capacity not exceeding "
                "1,500cc"
            ),
            "electric_category": (
                "Private Car (Electric), rated power not exceeding 75kW"
            ),
        },
        "base": {
            "combustion": extract_annual_fee(
                petrol,
                r"exceeding 1,500c\.c\. but not exceeding 2,500c\.c\.",
            ),
            "electric": extract_annual_fee(
                electric,
                r"exceeding 125kW but not exceeding 175kW",
            ),
            "combustion_category": (
                "Private Car (Petrol), cylinder capacity exceeding "
                "1,500cc but not exceeding 2,500cc"
            ),
            "electric_category": (
                "Private Car (Electric), rated power exceeding 125kW "
                "but not exceeding 175kW"
            ),
        },
        "high": {
            "combustion": extract_annual_fee(
                petrol,
                r"exceeding 2,500c\.c\. but not exceeding 3,500c\.c\.",
            ),
            "electric": extract_annual_fee(
                electric,
                r"\(e\).*?exceeding 225kW",
            ),
            "combustion_category": (
                "Private Car (Petrol), cylinder capacity exceeding "
                "2,500cc but not exceeding 3,500cc"
            ),
            "electric_category": (
                "Private Car (Electric), rated power exceeding 225kW"
            ),
        },
    }
    if "TD341 (Rev. 2/2026)" not in text:
        raise RuntimeError("TD341 revision marker not found on page 2")
    return extracted


def extract_parking_parameters() -> dict[str, Any]:
    housing_text = pdf_page_text(
        SOURCE_FILES["housing_parking"], 5
    )
    housing_match = re.search(
        r"Hong Kong and\s+Kowloon\s+90% or above\s+"
        r"([0-9,]+)\s+([0-9,]+)",
        housing_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if housing_match is None:
        raise RuntimeError(
            "Housing Authority Region A monthly parking row absent"
        )
    base_rate = integer_amount(housing_match.group(1))
    if (
        "Effective from 1 January to 31 December 2026"
        not in housing_text
    ):
        raise RuntimeError(
            "Housing Authority 2026 effective period absent"
        )

    government_text = pdf_page_text(
        SOURCE_FILES["government_parking_schedule"], 1
    )
    star_ferry_match = re.search(
        r"Star Ferry(.*?)City Hall",
        government_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if star_ferry_match is None:
        raise RuntimeError(
            "Star Ferry government car-park row absent"
        )
    high_match = re.search(
        r"\$([0-9,]+)\s+\(Monthly\)\s+\(Non-reserved\)",
        star_ferry_match.group(1),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if high_match is None:
        raise RuntimeError(
            "Star Ferry non-reserved monthly private-car rate absent"
        )
    high_rate = integer_amount(high_match.group(1))
    if "With effect from March 1, 2026" not in government_text:
        raise RuntimeError(
            "Government car-park March 2026 effective date absent"
        )
    return {
        "low": {
            "monthly": 0.0,
            "source_role": "analyst_sensitivity_exclusion",
            "source_page": "",
            "source_category": (
                "residential_parking_component_excluded_in_low_sensitivity"
            ),
            "effective_date": "",
            "official_value": False,
            "quality": (
                "analyst_component_exclusion_not_free_parking_claim"
            ),
        },
        "base": {
            "monthly": base_rate,
            "source_role": "housing_parking",
            "source_page": "PDF page 5 (Annex)",
            "source_category": (
                "Region A Hong Kong and Kowloon; occupancy 90% or "
                "above; Private Car; Full Time; Covered; monthly charge"
            ),
            "effective_date": "2026-01-01",
            "official_value": True,
            "quality": (
                "official_housing_authority_residential_monthly_fee_"
                "analyst_representative_scenario"
            ),
        },
        "high": {
            "monthly": high_rate,
            "source_role": "government_parking_schedule",
            "source_page": "PDF page 1",
            "source_category": (
                "Star Ferry government public car park; Private Car/"
                "Van; Monthly/Quarterly Rate; monthly non-reserved"
            ),
            "effective_date": "2026-03-01",
            "official_value": True,
            "quality": (
                "official_government_public_car_park_monthly_fee_"
                "analyst_high_proxy_not_observed_residential_fee"
            ),
        },
    }


def read_fleet_counts(path: Path) -> dict[str, float | int | str]:
    raw = pd.read_excel(path, header=None, dtype=object)
    text = raw.astype(str).apply(
        lambda row: " | ".join(row.tolist()), axis=1
    )
    candidates = text[
        text.str.contains("Private Cars", case=False, na=False)
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one Private Cars row in TD table T4.4"
        )
    row = raw.loc[candidates.index[0]]
    numeric: list[float] = []
    for value in row.tolist():
        try:
            number = float(
                str(value).replace(",", "").replace(" ", "")
            )
        except ValueError:
            continue
        if number >= 0:
            numeric.append(number)
    if len(numeric) < 14:
        raise RuntimeError(
            "TD table T4.4 private-car row is incomplete"
        )
    values = numeric[-14:]
    licensed = {
        "petrol": values[1],
        "diesel": values[3],
        "electric": values[5],
        "lpg": values[7],
        "hydrogen": values[9],
        "others": values[11],
        "total": values[13],
    }
    subtotal = sum(
        value for key, value in licensed.items() if key != "total"
    )
    if abs(subtotal - licensed["total"]) > FLOAT_TOLERANCE:
        raise RuntimeError(
            f"Licensed fleet counts do not conserve: {licensed}"
        )
    combustion = (
        licensed["petrol"]
        + licensed["diesel"]
        + licensed["lpg"]
        + licensed["hydrogen"]
        + licensed["others"]
    )
    return {
        **{f"licensed_{key}": value for key, value in licensed.items()},
        "licensed_combustion_proxy": combustion,
        "combustion_proxy_share": combustion / licensed["total"],
        "electric_share": licensed["electric"] / licensed["total"],
        "source_sheet": "T4.4",
        "source_row_zero_based": int(candidates.index[0]),
    }


def build_parameters(
    records: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    licence = extract_licence_parameters()
    parking = extract_parking_parameters()
    fleet = read_fleet_counts(SOURCE_FILES["fleet"])
    licence_record = records[SOURCE_IDS["licence"]]
    fleet_record = records[SOURCE_IDS["fleet"]]
    selection_rationale = {
        "low": (
            "Analyst low sensitivity selects the lowest audited petrol "
            "and electric representative classes and excludes the "
            "residential parking component; it does not claim free parking."
        ),
        "base": (
            "Analyst base sensitivity selects the 1,501-2,500cc petrol "
            "class, a middle electric rated-power class, and the official "
            "Housing Authority Region A covered full-time monthly charge."
        ),
        "high": (
            "Analyst high sensitivity selects a higher petrol class, the "
            "highest electric rated-power class, and an official central "
            "government public-car-park non-reserved monthly fee as an "
            "upper proxy; the parking fee is not observed residential cost."
        ),
    }
    quality = {
        "low": (
            "official_licence_fee_analyst_representative_classes_plus_"
            "explicit_low_parking_component_exclusion_partial_fixed_proxy"
        ),
        "base": (
            "official_fee_anchors_analyst_representative_classes_"
            "partial_fixed_proxy"
        ),
        "high": (
            "official_fee_anchors_analyst_high_sensitivity_nonresidential_"
            "parking_proxy_partial_fixed_proxy"
        ),
    }
    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        parking_role = str(parking[scenario]["source_role"])
        parking_record = (
            records[SOURCE_IDS[parking_role]]
            if parking_role in SOURCE_IDS
            else None
        )
        combustion_fee = float(licence[scenario]["combustion"])
        electric_fee = float(licence[scenario]["electric"])
        monthly_parking = float(parking[scenario]["monthly"])
        weighted_annual = (
            float(fleet["combustion_proxy_share"]) * combustion_fee
            + float(fleet["electric_share"]) * electric_fee
        )
        daily_licence = weighted_annual / ALLOCATION_DAYS
        daily_parking = monthly_parking * 12.0 / ALLOCATION_DAYS
        total = daily_licence + daily_parking
        parking_source_file = (
            repository_source_path(parking_record)
            if parking_record is not None
            else ""
        )
        parking_source_url = (
            str(parking_record["source_url"])
            if parking_record is not None
            else ""
        )
        parking_source_hash = (
            str(parking_record["file_sha256"])
            if parking_record is not None
            else ""
        )
        cost_sources = [repository_source_path(licence_record)]
        if parking_source_file:
            cost_sources.append(parking_source_file)
        else:
            cost_sources.append(
                "analyst_sensitivity:"
                "residential_parking_component_excluded_in_low_sensitivity"
            )
        rows.append(
            {
                "scenario": scenario,
                "fixed_cost_proxy_name": PROXY_NAME,
                "combustion_annual_licence_hkd": combustion_fee,
                "combustion_licence_category": (
                    licence[scenario]["combustion_category"]
                ),
                "electric_annual_licence_hkd": electric_fee,
                "electric_licence_category": (
                    licence[scenario]["electric_category"]
                ),
                "vehicle_licence_source_file": (
                    repository_source_path(licence_record)
                ),
                "vehicle_licence_source_url": str(
                    licence_record["source_url"]
                ),
                "vehicle_licence_source_sha256": str(
                    licence_record["file_sha256"]
                ),
                "vehicle_licence_source_page": (
                    "PDF page 2, Vehicle Licence table, Annual Fee column"
                ),
                "vehicle_licence_publisher": "Transport Department",
                "vehicle_licence_original_unit": "HKD/year",
                "vehicle_licence_effective_date": "2026-03-01",
                "vehicle_licence_value_status": (
                    "official_fee_analyst_representative_category"
                ),
                "residential_monthly_parking_proxy_hkd": (
                    monthly_parking
                ),
                "residential_parking_source_file": parking_source_file,
                "residential_parking_source_url": parking_source_url,
                "residential_parking_source_sha256": parking_source_hash,
                "residential_parking_source_page": (
                    parking[scenario]["source_page"]
                ),
                "residential_parking_source_category": (
                    parking[scenario]["source_category"]
                ),
                "residential_parking_publisher": (
                    str(parking_record["publisher"])
                    if parking_record is not None
                    else "analyst_sensitivity"
                ),
                "residential_parking_original_unit": "HKD/month",
                "residential_parking_effective_date": (
                    parking[scenario]["effective_date"]
                ),
                "residential_parking_value_official": bool(
                    parking[scenario]["official_value"]
                ),
                "residential_parking_value_quality": (
                    parking[scenario]["quality"]
                ),
                "combustion_proxy_share": fleet[
                    "combustion_proxy_share"
                ],
                "electric_share": fleet["electric_share"],
                "licensed_petrol": fleet["licensed_petrol"],
                "licensed_diesel": fleet["licensed_diesel"],
                "licensed_electric": fleet["licensed_electric"],
                "licensed_lpg": fleet["licensed_lpg"],
                "licensed_hydrogen": fleet["licensed_hydrogen"],
                "licensed_others": fleet["licensed_others"],
                "licensed_total": fleet["licensed_total"],
                "fleet_source_file": repository_source_path(
                    fleet_record
                ),
                "fleet_source_url": str(fleet_record["source_url"]),
                "fleet_source_sha256": str(
                    fleet_record["file_sha256"]
                ),
                "fleet_source_sheet": fleet["source_sheet"],
                "fleet_reference_date": "2025-12-31",
                "fleet_weighted_annual_licence_hkd": weighted_annual,
                "daily_licence_proxy_hkd": daily_licence,
                "daily_residential_parking_proxy_hkd": daily_parking,
                "fixed_vehicle_ownership_cost_hkd_per_vehicle_day": (
                    total
                ),
                "allocation_days_per_year": ALLOCATION_DAYS,
                "allocation_semantics": (
                    "annual_cost_model_day_allocation_convention_not_"
                    "an_actual_daily_payment"
                ),
                "selection_rationale": selection_rationale[scenario],
                "scenario_value_status": (
                    "analyst_sensitivity_not_individual_vehicle_"
                    "classification"
                ),
                "cost_source": "|".join(cost_sources),
                "cost_quality": quality[scenario],
                "candidate_reference_date": CANDIDATE_REFERENCE_DATE,
                "candidate_reference_date_semantics": (
                    "candidate_build_reference_date_not_a_claim_that_"
                    "component_sources_share_one_effective_date"
                ),
                "exclusions": EXCLUSIONS,
            }
        )
    return pd.DataFrame(rows), {
        "fleet": fleet,
        "licence_extraction": licence,
        "parking_extraction": parking,
        "parameter_origin": (
            "independently_extracted_from_frozen_official_pdf_and_xls_"
            "sources;old_csv_and_manifest_final_values_not_used"
        ),
    }


def load_vehicle_classes(path: Path) -> dict[str, str]:
    vehicles: dict[str, str] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "vehicle":
                vehicle_id = normalized_text(
                    element.attrib.get("id")
                )
                vehicle_class = normalized_text(
                    element.attrib.get("type")
                )
                if vehicle_id in vehicles:
                    raise RuntimeError(
                        f"Duplicate vehicle definition {vehicle_id}"
                    )
                vehicles[vehicle_id] = vehicle_class
            element.clear()
    return vehicles


def selected_plan(person: Any) -> Any | None:
    plans = [
        child for child in person if tag_name(child) == "plan"
    ]
    if not plans:
        return None
    selected = [
        plan
        for plan in plans
        if plan.attrib.get("selected", "yes").lower()
        in {"yes", "true", "1"}
    ]
    return selected[0] if selected else plans[0]


def person_attributes(person: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in person:
        if tag_name(child) != "attributes":
            continue
        for attribute in child:
            if tag_name(attribute) == "attribute":
                result[
                    normalized_text(attribute.attrib.get("name"))
                ] = normalized_text(attribute.text)
        break
    return result


def parse_time_s(value: object) -> float:
    text = normalized_text(value)
    if not text:
        return float("nan")
    try:
        return float(text)
    except ValueError:
        parts = text.split(":")
        if len(parts) != 3:
            return float("nan")
        try:
            hours, minutes, seconds = (
                float(part) for part in parts
            )
        except ValueError:
            return float("nan")
        return hours * 3600.0 + minutes * 60.0 + seconds


def main_activities_and_legs(
    plan: Any,
) -> tuple[list[Any], list[tuple[int, Any]]]:
    main_activities: list[Any] = []
    legs: list[tuple[int, Any]] = []
    main_activity_index = -1
    for child in plan:
        name = tag_name(child)
        if name == "activity":
            activity_type = normalized_text(
                child.attrib.get("type")
            )
            if not activity_type.endswith("interaction"):
                main_activity_index += 1
                main_activities.append(child)
        elif name == "leg":
            legs.append((main_activity_index, child))
    return main_activities, legs


def parse_routed_car_legs(
    path: Path,
    needed_keys: set[tuple[str, int]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    with gzip.open(path, "rb") as handle:
        context = etree.iterparse(
            handle,
            events=("end",),
            tag="person",
            huge_tree=True,
            recover=False,
        )
        for _, person in context:
            person_id = normalized_text(person.attrib.get("id"))
            plan = selected_plan(person)
            if plan is not None:
                attributes = person_attributes(person)
                activities, legs = main_activities_and_legs(plan)
                for sequence, leg in legs:
                    if normalized_text(
                        leg.attrib.get("mode")
                    ) != "car":
                        continue
                    key = (person_id, int(sequence))
                    if key in seen:
                        raise RuntimeError(
                            f"Duplicate routed car leg {key}"
                        )
                    seen.add(key)
                    if key not in needed_keys:
                        continue
                    route = next(
                        (
                            child
                            for child in leg
                            if tag_name(child) == "route"
                        ),
                        None,
                    )
                    vehicle_ref = (
                        normalized_text(
                            route.attrib.get("vehicleRefId")
                        )
                        if route is not None
                        else ""
                    )
                    departure = parse_time_s(
                        leg.attrib.get("dep_time")
                    )
                    travel = parse_time_s(
                        route.attrib.get("trav_time")
                        if route is not None
                        else leg.attrib.get("trav_time")
                    )
                    if not math.isfinite(travel):
                        travel = parse_time_s(
                            leg.attrib.get("trav_time")
                        )
                    origin = (
                        activities[sequence]
                        if 0 <= sequence < len(activities)
                        else None
                    )
                    destination = (
                        activities[sequence + 1]
                        if 0 <= sequence + 1 < len(activities)
                        else None
                    )
                    rows.append(
                        {
                            "person_id": person_id,
                            "leg_sequence": int(sequence),
                            "vehicle_ref_id": vehicle_ref,
                            "household_id": attributes.get(
                                "householdId", ""
                            ),
                            "assigned_vehicle_id": attributes.get(
                                "assignedVehicleId", ""
                            ),
                            "departure_time_s": departure,
                            "route_travel_time_s": travel,
                            "arrival_time_s": (
                                departure + travel
                                if math.isfinite(departure)
                                and math.isfinite(travel)
                                else float("nan")
                            ),
                            "origin_facility_id": (
                                normalized_text(
                                    origin.attrib.get("facility")
                                )
                                if origin is not None
                                else ""
                            ),
                            "destination_facility_id": (
                                normalized_text(
                                    destination.attrib.get("facility")
                                )
                                if destination is not None
                                else ""
                            ),
                        }
                    )
            person.clear()
            while person.getprevious() is not None:
                del person.getparent()[0]
    if seen != needed_keys:
        missing = len(needed_keys - seen)
        extra = len(seen - needed_keys)
        raise RuntimeError(
            "Routed/manifest car keys differ: "
            f"missing={missing}, extra={extra}"
        )
    return pd.DataFrame(rows)


def attach_chain_diagnostics(private: pd.DataFrame) -> pd.DataFrame:
    ordered = private.sort_values(
        [
            "vehicle_ref_id",
            "departure_time_s",
            "person_id",
            "leg_sequence",
        ],
        kind="mergesort",
    ).copy()
    grouped = ordered.groupby(
        "vehicle_ref_id", sort=False, dropna=False
    )
    ordered["next_departure_time_s"] = grouped[
        "departure_time_s"
    ].shift(-1)
    ordered["next_origin_facility_id"] = grouped[
        "origin_facility_id"
    ].shift(-1)
    has_next = ordered["next_departure_time_s"].notna()
    ordered["vehicle_chain_time_overlap"] = (
        has_next
        & ordered["arrival_time_s"].notna()
        & ordered["arrival_time_s"].gt(
            ordered["next_departure_time_s"]
        )
    )
    ordered["vehicle_chain_facility_mismatch"] = (
        has_next
        & ordered["destination_facility_id"].ne("")
        & ordered["next_origin_facility_id"].fillna("").ne("")
        & ordered["destination_facility_id"].ne(
            ordered["next_origin_facility_id"]
        )
    )
    return ordered


def build_vehicle_day_base(
    private: pd.DataFrame,
    household_ids: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    grouping = private.groupby(
        "vehicle_ref_id", sort=True, dropna=False
    ).agg(
        person_id=("person_id", "first"),
        person_count=("person_id", "nunique"),
        household_id=("household_id", "first"),
        household_count=("household_id", "nunique"),
        leg_count=("leg_sequence", "size"),
    ).reset_index()
    match_counts = (
        private.assign(
            assignment_match=private["assigned_vehicle_id"].eq(
                private["vehicle_ref_id"]
            )
        )
        .groupby("vehicle_ref_id")["assignment_match"]
        .sum()
    )
    grouping["assigned_vehicle_match_count"] = grouping[
        "vehicle_ref_id"
    ].map(match_counts).astype(int)
    grouping["household_in_synthetic_table"] = grouping[
        "household_id"
    ].isin(household_ids)
    grouping["vehicle_day_id"] = (
        grouping["vehicle_ref_id"]
        + "|typical_weekday_model_day"
    )
    diagnostics = {
        "unique_private_vehicles": int(len(grouping)),
        "vehicles_used_by_multiple_persons": int(
            grouping["person_count"].gt(1).sum()
        ),
        "vehicles_used_by_multiple_households": int(
            grouping["household_count"].gt(1).sum()
        ),
        "vehicles_with_person_mapping": int(
            grouping["person_id"].ne("").sum()
        ),
        "vehicles_with_household_mapping": int(
            grouping["household_id"].ne("").sum()
        ),
        "vehicles_with_household_in_synthetic_table": int(
            grouping["household_in_synthetic_table"].sum()
        ),
        "vehicles_with_all_leg_assignments_matching": int(
            grouping["assigned_vehicle_match_count"]
            .eq(grouping["leg_count"])
            .sum()
        ),
    }
    return grouping, diagnostics


def apply_scenario(
    vehicles: pd.DataFrame,
    parameter: pd.Series,
    scenario: str,
) -> pd.DataFrame:
    frame = vehicles[
        ["person_id", "household_id", "vehicle_ref_id", "vehicle_day_id"]
    ].copy()
    frame["person_id_semantics"] = (
        "unique_plan_user_not_legal_owner_claim"
    )
    frame["leg_sequence"] = -1
    frame["mode"] = "car"
    frame["vehicle_class"] = "private_car"
    frame["scenario"] = scenario
    frame["cost_component"] = "fixed_vehicle_ownership_cost"
    frame["fixed_cost_proxy_name"] = PROXY_NAME
    frame["cost_hkd"] = float(
        parameter[
            "fixed_vehicle_ownership_cost_hkd_per_vehicle_day"
        ]
    )
    frame["cost_source"] = str(parameter["cost_source"])
    frame["cost_effective_date"] = ""
    frame["cost_effective_date_status"] = (
        "not_single_date_mixed_component_effective_dates_"
        "see_separate_fields"
    )
    frame["cost_quality"] = str(parameter["cost_quality"])
    frame["record_scope"] = RECORD_SCOPE
    frame["owner_observed"] = False
    frame["vehicle_powertrain"] = FLEET_PROXY
    frame["individual_engine_displacement_observed"] = False
    frame["individual_rated_power_observed"] = False
    frame["combustion_proxy_share"] = float(
        parameter["combustion_proxy_share"]
    )
    frame["electric_share"] = float(parameter["electric_share"])
    frame["combustion_annual_licence_hkd"] = float(
        parameter["combustion_annual_licence_hkd"]
    )
    frame["electric_annual_licence_hkd"] = float(
        parameter["electric_annual_licence_hkd"]
    )
    frame["annual_licence_proxy_hkd"] = float(
        parameter["fleet_weighted_annual_licence_hkd"]
    )
    frame["daily_licence_proxy_hkd"] = float(
        parameter["daily_licence_proxy_hkd"]
    )
    frame["residential_monthly_parking_proxy_hkd"] = float(
        parameter["residential_monthly_parking_proxy_hkd"]
    )
    frame["daily_residential_parking_proxy_hkd"] = float(
        parameter["daily_residential_parking_proxy_hkd"]
    )
    frame["allocation_days_per_year"] = ALLOCATION_DAYS
    frame["allocation_semantics"] = str(
        parameter["allocation_semantics"]
    )
    frame["vehicle_licence_effective_date"] = str(
        parameter["vehicle_licence_effective_date"]
    )
    frame["residential_parking_effective_date"] = str(
        parameter["residential_parking_effective_date"]
    )
    frame["candidate_reference_date"] = CANDIDATE_REFERENCE_DATE
    frame["candidate_reference_date_semantics"] = str(
        parameter["candidate_reference_date_semantics"]
    )
    frame["exclusions"] = EXCLUSIONS
    frame["assumption_status"] = (
        "partial_fixed_vehicle_ownership_proxy;"
        "representative_fleet_and_fee_categories_not_individual_"
        "vehicle_recognition;"
        + (
            "residential_parking_component_excluded_in_low_sensitivity"
            if scenario == "low"
            else (
                "official_residential_monthly_fee_used_as_analyst_proxy"
                if scenario == "base"
                else (
                    "government_public_car_park_monthly_fee_used_as_"
                    "analyst_high_proxy_not_observed_residential_fee"
                )
            )
        )
    )
    return frame[OUTPUT_COLUMNS]


def old_parameter_comparison(
    parameters: pd.DataFrame,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    old_manifest = {
        str(row["scenario"]): row
        for row in manifest["fixed_vehicle_ownership_cost_parameters"]
    }
    old_energy = pd.read_csv(OLD_ENERGY_PARAMETERS_PATH).set_index(
        "scenario"
    )
    audited_energy = pd.read_csv(ENERGY_PARAMETERS_PATH).set_index(
        "scenario"
    )
    values: dict[str, Any] = {}
    for row in parameters.itertuples(index=False):
        old = old_manifest[str(row.scenario)]
        values[str(row.scenario)] = {
            "prototype_combustion_annual_licence_difference_hkd": (
                float(row.combustion_annual_licence_hkd)
                - float(old["combustion_annual_licence_hkd"])
            ),
            "prototype_electric_annual_licence_difference_hkd": (
                float(row.electric_annual_licence_hkd)
                - float(old["electric_annual_licence_hkd"])
            ),
            "prototype_residential_monthly_parking_difference_hkd": (
                float(row.residential_monthly_parking_proxy_hkd)
                - float(old["residential_monthly_parking_hkd"])
            ),
            "old_energy_combustion_share_difference": (
                float(row.combustion_proxy_share)
                - float(
                    old_energy.loc[
                        row.scenario, "combustion_proxy_share"
                    ]
                )
            ),
            "old_energy_electric_share_difference": (
                float(row.electric_share)
                - float(
                    old_energy.loc[row.scenario, "electric_share"]
                )
            ),
            "audited_energy_combustion_share_difference": (
                float(row.combustion_proxy_share)
                - float(
                    audited_energy.loc[
                        row.scenario, "combustion_proxy_share"
                    ]
                )
            ),
            "audited_energy_electric_share_difference": (
                float(row.electric_share)
                - float(
                    audited_energy.loc[
                        row.scenario, "electric_share"
                    ]
                )
            ),
        }
    return {
        "comparison_only_not_parameter_input": True,
        "parameters_reconstructed_before_comparison": True,
        "differences": values,
    }


def build_summary(
    frames: dict[str, pd.DataFrame],
    parameters: pd.DataFrame,
) -> pd.DataFrame:
    parameter_index = parameters.set_index("scenario")
    rows = []
    for scenario in SCENARIOS:
        frame = frames[scenario]
        parameter = parameter_index.loc[scenario]
        rows.append(
            {
                "scenario": scenario,
                "unique_vehicle_days": int(len(frame)),
                "fixed_cost_proxy_name": PROXY_NAME,
                "daily_licence_proxy_hkd_per_vehicle": float(
                    parameter["daily_licence_proxy_hkd"]
                ),
                "daily_residential_parking_proxy_hkd_per_vehicle": (
                    float(
                        parameter[
                            "daily_residential_parking_proxy_hkd"
                        ]
                    )
                ),
                "fixed_ownership_cost_hkd_per_vehicle_day": float(
                    parameter[
                        "fixed_vehicle_ownership_cost_hkd_per_vehicle_day"
                    ]
                ),
                "total_licence_proxy_hkd": float(
                    frame["daily_licence_proxy_hkd"].sum()
                ),
                "total_residential_parking_proxy_hkd": float(
                    frame[
                        "daily_residential_parking_proxy_hkd"
                    ].sum()
                ),
                "total_fixed_ownership_cost_hkd": float(
                    frame["cost_hkd"].sum()
                ),
                "mean_hkd": float(frame["cost_hkd"].mean()),
                "median_hkd": float(frame["cost_hkd"].median()),
                "p90_hkd": float(frame["cost_hkd"].quantile(0.9)),
                "cost_quality": str(parameter["cost_quality"]),
            }
        )
    return pd.DataFrame(rows)


def validate(
    legs: pd.DataFrame,
    private: pd.DataFrame,
    chain: pd.DataFrame,
    vehicles: pd.DataFrame,
    mapping: dict[str, Any],
    parameters: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    manifest_car_keys: set[tuple[str, int]],
    feasibility: pd.DataFrame,
    diagnostics: dict[str, Any],
    old_comparison: dict[str, Any],
) -> dict[str, Any]:
    parameter_index = parameters.set_index("scenario")
    scenario_checks: dict[str, Any] = {}
    formula_errors: dict[str, float] = {}
    for scenario in SCENARIOS:
        frame = frames[scenario]
        parameter = parameter_index.loc[scenario]
        expected_total = float(
            parameter["daily_licence_proxy_hkd"]
            + parameter["daily_residential_parking_proxy_hkd"]
        )
        recomputed_annual = float(
            parameter["combustion_proxy_share"]
            * parameter["combustion_annual_licence_hkd"]
            + parameter["electric_share"]
            * parameter["electric_annual_licence_hkd"]
        )
        errors = [
            abs(
                recomputed_annual
                - float(
                    parameter["fleet_weighted_annual_licence_hkd"]
                )
            ),
            abs(
                recomputed_annual / ALLOCATION_DAYS
                - float(parameter["daily_licence_proxy_hkd"])
            ),
            abs(
                float(
                    parameter[
                        "residential_monthly_parking_proxy_hkd"
                    ]
                )
                * 12.0
                / ALLOCATION_DAYS
                - float(
                    parameter[
                        "daily_residential_parking_proxy_hkd"
                    ]
                )
            ),
            abs(
                expected_total
                - float(
                    parameter[
                        "fixed_vehicle_ownership_cost_hkd_per_vehicle_day"
                    ]
                )
            ),
        ]
        formula_errors[scenario] = float(max(errors))
        collisions = sum(
            (person, int(sequence)) in manifest_car_keys
            for person, sequence in zip(
                frame["person_id"],
                frame["leg_sequence"],
                strict=False,
            )
        )
        rate = float(
            parameter[
                "fixed_vehicle_ownership_cost_hkd_per_vehicle_day"
            ]
        )
        scenario_checks[scenario] = {
            "row_count": int(len(frame)),
            "unique_vehicle_count": int(
                frame["vehicle_ref_id"].nunique()
            ),
            "vehicle_ref_id_unique": bool(
                ~frame["vehicle_ref_id"].duplicated().any()
            ),
            "motorcycle_record_count": int(
                frame["vehicle_class"].eq("motorcycle").sum()
            ),
            "normal_leg_sequence_count": int(
                frame["leg_sequence"].ge(0).sum()
            ),
            "person_normal_leg_key_collision_count": int(collisions),
            "cost_non_negative": bool(frame["cost_hkd"].ge(0).all()),
            "cost_component_valid": bool(
                frame["cost_component"]
                .eq("fixed_vehicle_ownership_cost")
                .all()
            ),
            "record_scope_valid": bool(
                frame["record_scope"].eq(RECORD_SCOPE).all()
            ),
            "owner_observed_false": bool(
                ~frame["owner_observed"].any()
            ),
            "total_cost_hkd": float(frame["cost_hkd"].sum()),
            "vehicle_count_times_rate_hkd": float(
                len(frame) * rate
            ),
            "sum_minus_vehicle_count_times_rate_hkd": float(
                frame["cost_hkd"].sum() - len(frame) * rate
            ),
            "child_component_sum_max_abs_error_hkd": float(
                (
                    frame["daily_licence_proxy_hkd"]
                    + frame[
                        "daily_residential_parking_proxy_hkd"
                    ]
                    - frame["cost_hkd"]
                )
                .abs()
                .max()
            ),
        }
    stacked = pd.concat(
        [frames[scenario] for scenario in SCENARIOS],
        ignore_index=True,
    )
    pivot = stacked.pivot(
        index="vehicle_ref_id",
        columns="scenario",
        values="cost_hkd",
    )
    order_valid = bool(
        pivot["low"].le(pivot["base"]).all()
        and pivot["base"].le(pivot["high"]).all()
    )
    feasibility_private = feasibility.loc[
        feasibility["vehicle_class"].eq("private_car")
    ].copy()
    independent_vehicle_set = set(
        private["vehicle_ref_id"].astype(str)
    )
    feasibility_vehicle_set = set(
        feasibility_private["vehicle_ref_id"].astype(str)
    )
    hard_checks = {
        "car_leg_count_67718": len(legs) == 67718,
        "private_car_leg_count_64789": len(private) == 64789,
        "motorcycle_leg_count_2929": (
            int(legs["vehicle_class"].eq("motorcycle").sum()) == 2929
        ),
        "missing_vehicle_ref_id_zero": (
            int(legs["vehicle_ref_id"].eq("").sum()) == 0
        ),
        "used_private_vehicle_count_21020": len(vehicles) == 21020,
        "independent_vehicle_set_matches_feasibility": (
            independent_vehicle_set == feasibility_vehicle_set
        ),
        "vehicle_person_mapping_complete": (
            mapping["vehicles_with_person_mapping"] == 21020
        ),
        "vehicle_household_mapping_complete": (
            mapping["vehicles_with_household_mapping"] == 21020
        ),
        "vehicle_household_synthetic_mapping_complete": (
            mapping["vehicles_with_household_in_synthetic_table"]
            == 21020
        ),
        "assigned_vehicle_mapping_complete": (
            mapping[
                "vehicles_with_all_leg_assignments_matching"
            ]
            == 21020
        ),
        "no_vehicle_used_by_multiple_persons": (
            mapping["vehicles_used_by_multiple_persons"] == 0
        ),
        "no_vehicle_used_by_multiple_households": (
            mapping["vehicles_used_by_multiple_households"] == 0
        ),
        "scenario_row_counts": all(
            scenario_checks[scenario]["row_count"] == 21020
            for scenario in SCENARIOS
        ),
        "all_scenario_total_rows_63060": len(stacked) == 63060,
        "one_record_per_vehicle_scenario": bool(
            ~stacked.duplicated(
                ["vehicle_ref_id", "scenario"]
            ).any()
        ),
        "all_vehicle_refs_unique_per_scenario": all(
            scenario_checks[scenario]["vehicle_ref_id_unique"]
            for scenario in SCENARIOS
        ),
        "no_motorcycle_records": all(
            scenario_checks[scenario]["motorcycle_record_count"] == 0
            for scenario in SCENARIOS
        ),
        "no_normal_leg_sequences": all(
            scenario_checks[scenario]["normal_leg_sequence_count"] == 0
            for scenario in SCENARIOS
        ),
        "no_person_normal_leg_key_collisions": all(
            scenario_checks[scenario][
                "person_normal_leg_key_collision_count"
            ]
            == 0
            for scenario in SCENARIOS
        ),
        "non_negative_costs": all(
            scenario_checks[scenario]["cost_non_negative"]
            for scenario in SCENARIOS
        ),
        "low_le_base_le_high": order_valid,
        "total_equals_vehicle_count_times_rate": all(
            abs(
                scenario_checks[scenario][
                    "sum_minus_vehicle_count_times_rate_hkd"
                ]
            )
            <= FLOAT_TOLERANCE
            for scenario in SCENARIOS
        ),
        "licence_plus_parking_equals_total": all(
            scenario_checks[scenario][
                "child_component_sum_max_abs_error_hkd"
            ]
            <= FLOAT_TOLERANCE
            for scenario in SCENARIOS
        ),
        "parameter_formulas_reproducible": all(
            error <= FLOAT_TOLERANCE
            for error in formula_errors.values()
        ),
        "parameters_not_copied_from_old_csv": (
            diagnostics["parameter_origin"].startswith(
                "independently_extracted"
            )
            and old_comparison[
                "parameters_reconstructed_before_comparison"
            ]
        ),
        "owner_observed_false": all(
            scenario_checks[scenario]["owner_observed_false"]
            for scenario in SCENARIOS
        ),
    }
    publishable = all(hard_checks.values())
    overlap_events = int(
        chain["vehicle_chain_time_overlap"].sum()
    )
    mismatch_events = int(
        chain["vehicle_chain_facility_mismatch"].sum()
    )
    overlap_vehicles = int(
        chain.loc[
            chain["vehicle_chain_time_overlap"], "vehicle_ref_id"
        ].nunique()
    )
    mismatch_vehicles = int(
        chain.loc[
            chain["vehicle_chain_facility_mismatch"],
            "vehicle_ref_id",
        ].nunique()
    )
    return {
        "audit": (
            "Hong Kong private-car fixed-ownership vehicle-day "
            "application v1"
        ),
        "source_commit": SOURCE_COMMIT,
        "candidate_output_only": True,
        "publishable_candidate": publishable,
        "blocked": not publishable,
        "matsim_scoring_modified": False,
        "unified_car_cost_modified": False,
        "energy_candidate_modified": False,
        "toll_candidate_modified": False,
        "parking_candidate_modified": False,
        "cost_boundary": {
            "proxy_name": PROXY_NAME,
            "complete_total_cost_of_ownership_claimed": False,
            "included": [
                "annual_vehicle_licence_fee_proxy",
                "residential_monthly_parking_proxy",
            ],
            "excluded": EXCLUSIONS.split("|"),
            "fixed_cost_attached_to_normal_leg": False,
            "allocation_days_per_year": ALLOCATION_DAYS,
            "allocation_semantics": (
                "annual_cost_model_day_allocation_convention_not_"
                "an_actual_daily_payment"
            ),
        },
        "charging_object_reconstruction": {
            "car_legs": int(len(legs)),
            "private_car_legs": int(len(private)),
            "motorcycle_legs_out_of_scope": int(
                legs["vehicle_class"].eq("motorcycle").sum()
            ),
            "missing_vehicle_ref_id": int(
                legs["vehicle_ref_id"].eq("").sum()
            ),
            "used_private_cars": int(len(vehicles)),
            "duplicate_vehicle_days_before_scenario_expansion": int(
                vehicles["vehicle_ref_id"].duplicated().sum()
            ),
            "vehicles_used_by_multiple_persons": mapping[
                "vehicles_used_by_multiple_persons"
            ],
            "vehicles_used_by_multiple_households": mapping[
                "vehicles_used_by_multiple_households"
            ],
            "vehicle_person_household_mapping": mapping,
            "vehicle_person_household_mapping_coverage": float(
                min(
                    mapping["vehicles_with_person_mapping"],
                    mapping["vehicles_with_household_mapping"],
                    mapping[
                        "vehicles_with_household_in_synthetic_table"
                    ],
                )
                / len(vehicles)
            ),
            "owner_observed": False,
            "owner_semantics": (
                "plan_user_and_household_assignment_are_not_legal_"
                "ownership_observations"
            ),
        },
        "vehicle_chain_diagnostics": {
            "time_overlap_events": overlap_events,
            "vehicles_with_time_overlap": overlap_vehicles,
            "next_departure_facility_mismatch_events": mismatch_events,
            "vehicles_with_facility_mismatch": mismatch_vehicles,
            "extra_fixed_charge_from_time_overlap": 0,
            "extra_fixed_charge_from_facility_mismatch": 0,
            "impact": (
                "diagnostic_only_unique_vehicle_ref_id_charged_once_"
                "per_scenario"
            ),
        },
        "fleet_composition_recalculation": diagnostics["fleet"],
        "parameter_source_audit": {
            "parameter_origin": diagnostics["parameter_origin"],
            "licence_pdf_page": 2,
            "housing_authority_pdf_page": 5,
            "government_parking_schedule_pdf_page": 1,
            "government_parking_html_used_as_parameter_source": False,
            "government_parking_html_reason": (
                "frozen_and_hash_protected_but_4850_is_precisely_"
                "sourced_from_the_official_pdf_schedule"
            ),
            "vehicle_file_engine_displacement_available": False,
            "vehicle_file_rated_power_available": False,
            "scenario_categories_are_individual_vehicle_recognition": (
                False
            ),
            "old_prototype_comparison": old_comparison,
            "scenario_parameters": {
                str(row.scenario): {
                    "combustion_annual_licence_hkd": float(
                        row.combustion_annual_licence_hkd
                    ),
                    "combustion_licence_category": str(
                        row.combustion_licence_category
                    ),
                    "electric_annual_licence_hkd": float(
                        row.electric_annual_licence_hkd
                    ),
                    "electric_licence_category": str(
                        row.electric_licence_category
                    ),
                    "residential_monthly_parking_proxy_hkd": float(
                        row.residential_monthly_parking_proxy_hkd
                    ),
                    "residential_parking_source_category": str(
                        row.residential_parking_source_category
                    ),
                    "vehicle_licence_effective_date": str(
                        row.vehicle_licence_effective_date
                    ),
                    "residential_parking_effective_date": str(
                        row.residential_parking_effective_date
                    ),
                    "daily_licence_proxy_hkd": float(
                        row.daily_licence_proxy_hkd
                    ),
                    "daily_residential_parking_proxy_hkd": float(
                        row.daily_residential_parking_proxy_hkd
                    ),
                    "fixed_vehicle_ownership_cost_hkd_per_vehicle_day": (
                        float(
                            row.fixed_vehicle_ownership_cost_hkd_per_vehicle_day
                        )
                    ),
                    "cost_quality": str(row.cost_quality),
                }
                for row in parameters.itertuples(index=False)
            },
            "parameter_formula_max_abs_error": formula_errors,
        },
        "scenario_outputs": scenario_checks,
        "all_scenarios_total_rows": int(len(stacked)),
        "hard_checks": hard_checks,
    }


def required_repairs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "repair_id": "FIXED-R01",
                "severity": "medium",
                "blocking": False,
                "component": "legal_ownership",
                "finding": (
                    "Canonical plans identify the unique vehicle user and "
                    "household assignment, not the observed legal owner."
                ),
                "required_change": (
                    "Keep owner_observed=false unless a separately audited "
                    "legal-ownership source becomes available."
                ),
            },
            {
                "repair_id": "FIXED-R02",
                "severity": "medium",
                "blocking": False,
                "component": "licence_category",
                "finding": (
                    "Private vehicles have no engine displacement or rated "
                    "power, so licence tiers are analyst scenarios."
                ),
                "required_change": (
                    "Do not assign a licence tier to an individual vehicle "
                    "without sourced engine or rated-power attributes."
                ),
            },
            {
                "repair_id": "FIXED-R03",
                "severity": "medium",
                "blocking": False,
                "component": "high_parking_proxy",
                "finding": (
                    "The high HKD 4,850 anchor is an official government "
                    "public-car-park monthly fee, not observed residential "
                    "parking for each modeled vehicle."
                ),
                "required_change": (
                    "Retain the explicit high-sensitivity proxy label; "
                    "replace it only with an audited residential distribution."
                ),
            },
            {
                "repair_id": "FIXED-R04",
                "severity": "medium",
                "blocking": False,
                "component": "partial_tco",
                "finding": (
                    "Depreciation, purchase, finance, insurance, maintenance, "
                    "tyres, and inspection are intentionally excluded."
                ),
                "required_change": (
                    "Do not call this candidate complete total cost of "
                    "ownership; add omitted components only in a new audit."
                ),
            },
            {
                "repair_id": "FIXED-R05",
                "severity": "low",
                "blocking": False,
                "component": "low_parking_sensitivity",
                "finding": (
                    "Low parking is an analyst component exclusion, not "
                    "evidence that modeled owners receive free parking."
                ),
                "required_change": (
                    "Preserve status residential_parking_component_excluded_"
                    "in_low_sensitivity in every reuse."
                ),
            },
        ]
    )


def main() -> None:
    args = parse_args()
    input_root = args.input_project_root.resolve()
    canonical = canonical_paths(input_root)
    required = {
        **SOURCE_FILES,
        "source_manifest": SOURCE_MANIFEST_PATH,
        "feasibility": FEASIBILITY_PATH,
        "old_energy_parameters": OLD_ENERGY_PARAMETERS_PATH,
        "audited_energy_parameters": ENERGY_PARAMETERS_PATH,
    }
    missing = [key for key, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing local fixed-ownership inputs: {missing}"
        )

    protected = protected_paths(args.output_dir)
    protected_before = hash_map(protected)
    canonical_before = hash_map(canonical)
    manifest, source_records = load_source_manifest()
    parameters, parameter_diagnostics = build_parameters(
        source_records
    )
    old_comparison = old_parameter_comparison(
        parameters, manifest
    )

    trip_manifest = pd.read_parquet(canonical["trip_manifest"])
    manifest_car = trip_manifest.loc[
        trip_manifest["mode"].eq("car")
    ].copy()
    manifest_car["person_id"] = manifest_car[
        "person_id"
    ].astype(str)
    manifest_car["leg_sequence"] = manifest_car[
        "leg_sequence"
    ].astype(int)
    if manifest_car.duplicated(
        ["person_id", "leg_sequence"]
    ).any():
        raise RuntimeError(
            "Duplicate person/leg keys in car trip manifest"
        )
    manifest_car_keys = set(
        zip(
            manifest_car["person_id"],
            manifest_car["leg_sequence"],
            strict=False,
        )
    )
    legs = parse_routed_car_legs(
        canonical["plans_routed"], manifest_car_keys
    )
    vehicle_classes = load_vehicle_classes(
        canonical["private_vehicles"]
    )
    legs["vehicle_class"] = legs["vehicle_ref_id"].map(
        vehicle_classes
    ).fillna("unresolved")
    private = legs.loc[
        legs["vehicle_class"].eq("private_car")
    ].copy()
    chain = attach_chain_diagnostics(private)

    households = pd.read_parquet(
        canonical["synthetic_households"],
        columns=["household_id"],
    )
    household_ids = set(households["household_id"].astype(str))
    vehicles, mapping = build_vehicle_day_base(
        private, household_ids
    )
    feasibility = pd.read_parquet(FEASIBILITY_PATH)

    parameter_index = parameters.set_index("scenario")
    frames = {
        scenario: apply_scenario(
            vehicles, parameter_index.loc[scenario], scenario
        )
        for scenario in SCENARIOS
    }
    summary = build_summary(frames, parameters)
    validation = validate(
        legs,
        private,
        chain,
        vehicles,
        mapping,
        parameters,
        frames,
        manifest_car_keys,
        feasibility,
        parameter_diagnostics,
        old_comparison,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    parameters.to_csv(
        args.output_dir
        / "fixed_ownership_parameters_repository_relative.csv",
        index=False,
        encoding="utf-8",
    )
    for scenario, frame in frames.items():
        frame.to_parquet(
            args.output_dir
            / f"vehicle_day_fixed_ownership_costs_{scenario}.parquet",
            index=False,
        )
    summary.to_csv(
        args.output_dir / "fixed_ownership_application_summary.csv",
        index=False,
        encoding="utf-8",
    )
    repairs = required_repairs()
    repairs.to_csv(
        args.output_dir
        / "fixed_ownership_application_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )

    protected_after = hash_map(protected)
    canonical_after = hash_map(canonical)
    protected_unchanged = protected_before == protected_after
    canonical_unchanged = canonical_before == canonical_after

    def subset_unchanged(fragment: str) -> bool:
        keys = [
            key for key in protected_before if fragment in key
        ]
        return bool(keys) and all(
            protected_before[key] == protected_after[key]
            for key in keys
        )

    source_manifest_checks = {}
    for source_id, record in {
        str(row["source_id"]): row for row in manifest["sources"]
    }.items():
        path = CAR_COST_ROOT / str(record["source_file"])
        actual = sha256_file(path)
        source_manifest_checks[source_id] = {
            "source_path": path.as_posix(),
            "manifest_sha256": str(record["file_sha256"]),
            "actual_sha256": actual,
            "matches": actual == str(record["file_sha256"]),
        }
    all_source_manifest_hashes_match = all(
        value["matches"]
        for value in source_manifest_checks.values()
    )
    protection = {
        "canonical_inputs_unchanged": canonical_unchanged,
        "all_existing_car_cost_files_unchanged": (
            protected_unchanged
        ),
        "source_snapshots_unchanged": subset_unchanged(
            "source_snapshots/"
        ),
        "energy_application_v1_unchanged": subset_unchanged(
            "energy_application_v1/"
        ),
        "parking_event_application_v1_unchanged": subset_unchanged(
            "parking_event_application_v1/"
        ),
        "toll_network_mapping_v1_unchanged": subset_unchanged(
            "toll_network_mapping_v1/"
        ),
        "toll_rate_application_v1_unchanged": subset_unchanged(
            "toll_rate_application_v1/"
        ),
        "all_source_snapshot_manifest_hashes_match": (
            all_source_manifest_hashes_match
        ),
        "all_protected_sha256_unchanged": bool(
            canonical_unchanged
            and protected_unchanged
            and all_source_manifest_hashes_match
        ),
    }
    validation["protected_inputs"] = protection
    validation["required_repairs"] = {
        "row_count": int(len(repairs)),
        "blocking_count": int(repairs["blocking"].sum()),
        "all_are_documented_nonblocking_limitations": bool(
            ~repairs["blocking"].any()
        ),
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
        "existing_car_cost_hashes_before": protected_before,
        "existing_car_cost_hashes_after": protected_after,
        "source_snapshot_manifest_checks": source_manifest_checks,
        "parameter_source_roles": {
            "vehicle_licence": (
                "td_vehicle_licence_fees_2026 PDF page 2"
            ),
            "base_residential_parking": (
                "housing_authority_carpark_fees_2026 PDF page 5"
            ),
            "high_parking_proxy": (
                "td_parking_fees_2026 PDF page 1"
            ),
            "fleet_shares": (
                "td_vehicle_fuel_type_2025_12 XLS sheet T4.4"
            ),
            "td_government_car_parks_html": (
                "hash_protected_not_used_as_parameter_source"
            ),
        },
        "all_protected_sha256_unchanged": protection[
            "all_protected_sha256_unchanged"
        ],
    }
    write_json(
        args.output_dir
        / "fixed_ownership_application_validation.json",
        validation,
    )
    write_json(
        args.output_dir
        / "fixed_ownership_application_input_hashes.json",
        hashes,
    )
    if validation["blocked"]:
        raise RuntimeError(
            "Fixed-ownership candidate failed a hard-stop validation"
        )
    print(
        json.dumps(
            {
                "output_dir": args.output_dir.as_posix(),
                "publishable_candidate": True,
                "private_car_legs": int(len(private)),
                "used_private_cars": int(len(vehicles)),
                "motorcycles_out_of_scope": int(
                    legs["vehicle_class"].eq("motorcycle").sum()
                ),
                "scenario_rates_hkd_per_vehicle_day": {
                    scenario: float(
                        parameter_index.loc[
                            scenario,
                            (
                                "fixed_vehicle_ownership_cost_hkd_"
                                "per_vehicle_day"
                            ),
                        ]
                    )
                    for scenario in SCENARIOS
                },
                "scenario_totals_hkd": {
                    scenario: float(
                        frames[scenario]["cost_hkd"].sum()
                    )
                    for scenario in SCENARIOS
                },
                "all_protected_sha256_unchanged": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
