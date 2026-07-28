#!/usr/bin/env python3
"""Build an audited Hong Kong representative-fleet energy-cost candidate.

The output is an offline fuel-or-electricity candidate. It never assigns an
individual powertrain and does not modify MATSim inputs, scoring, tolls,
parking, fixed ownership costs, or the existing unified car-cost outputs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from lxml import etree


CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
DEFAULT_OUTPUT = CAR_COST_ROOT / "energy_application_v1"
SOURCE_MANIFEST_PATH = CAR_COST_ROOT / "car_cost_source_manifest.json"
OLD_PARAMETERS_PATH = CAR_COST_ROOT / "car_energy_cost_parameters.csv"
FEASIBILITY_ROOT = CAR_COST_ROOT / "input_feasibility"
SCENARIOS = ("low", "base", "high")
SOURCE_COMMIT = "a2c6286c8c382222af784ec357e9b14abb77a2c5"
POWERTRAIN_PROXY = "representative_hk_private_car_fleet_average_proxy"
PROXY_ASSIGNMENT_SCOPE = (
    "fleet_average_applied_to_each_private_car_leg"
)
COST_QUALITY = (
    "official_sources_representative_licensed_fleet_average_proxy_"
    "no_individual_powertrain"
)
FLOAT_TOLERANCE = 1e-12
DISTANCE_TOLERANCE_M = 1e-8

SOURCE_FILES = {
    "oil": (
        CAR_COST_ROOT
        / "source_snapshots/consumer_oil_price.html"
    ),
    "consumption": (
        CAR_COST_ROOT
        / "source_snapshots/government_private_car_energy_consumption.html"
    ),
    "tariff": (
        CAR_COST_ROOT
        / "source_snapshots/government_electricity_tariff_2026.html"
    ),
    "fleet": (
        CAR_COST_ROOT
        / "source_snapshots/td_vehicle_fuel_type_2025_12.xls"
    ),
}
INPUT_DOCS = {
    "car_cost_model_document": Path(
        "docs/HONG_KONG_CAR_COST_MODEL.md"
    ),
    "toll_candidate_document": Path(
        "docs/HONG_KONG_PRIVATE_CAR_TOLL_RATE_APPLICATION.md"
    ),
    "parking_candidate_document": Path(
        "docs/HONG_KONG_PRIVATE_CAR_PARKING_EVENT_APPLICATION.md"
    ),
}
FEASIBILITY_INPUTS = {
    "feasibility_table": (
        FEASIBILITY_ROOT / "car_leg_input_feasibility.parquet"
    ),
    "feasibility_validation": (
        FEASIBILITY_ROOT / "car_cost_feasibility_validation.json"
    ),
    "feasibility_repairs": FEASIBILITY_ROOT / "required_repairs.csv",
}
CLP_CUSTOMER_REFERENCE_URL = (
    "https://www.clpgroup.com/en/about/our-business/assets-and-services/"
    "hong-kong/customer-services.html"
)
HKE_CUSTOMER_REFERENCE_URL = (
    "https://www.hkelectric.com/documents/en/InvestorRelations/Documents/"
    "Financial%20Reports/2025/AR/2025_HKEI_AR_E_04.pdf"
)

OUTPUT_COLUMNS = [
    "person_id",
    "leg_sequence",
    "vehicle_ref_id",
    "vehicle_class",
    "mode",
    "route_distance_m",
    "route_distance_quality",
    "route_start_link_id",
    "route_end_link_id",
    "route_link_count",
    "route_interior_link_count",
    "complete_link_sequence_length_m",
    "matsim_distance_convention_expected_m",
    "route_minus_link_sequence_distance_m",
    "route_minus_convention_expected_m",
    "route_minus_link_sequence_relative",
    "manifest_distance_field_available",
    "manifest_route_distance_m",
    "manifest_route_distance_difference_m",
    "zero_distance_classification",
    "vehicle_powertrain",
    "individual_powertrain_observed",
    "combustion_proxy_share",
    "electric_share",
    "combustion_cost_hkd_per_km",
    "electric_cost_hkd_per_km",
    "energy_cost_hkd_per_km",
    "fleet_weighted_combustion_contribution_hkd_per_km",
    "fleet_weighted_electric_contribution_hkd_per_km",
    "fleet_weighted_combustion_contribution_hkd",
    "fleet_weighted_electric_contribution_hkd",
    "cost_component",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_quality",
    "scenario",
    "energy_status",
    "unresolved_reason",
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


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def normalized_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bundle(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: value.name):
        encoded = path.name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


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
        "private_vehicles": demand / "privateVehicles_5pct.xml.gz",
        "trip_manifest": demand / "agent_trip_manifest_v2.parquet",
        "facilities": demand / "facilities_5pct_v2.xml.gz",
        "config": (
            demand
            / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ),
        "network": supply / "network.xml.gz",
        "synthetic_households": (
            input_root
            / "data/matsim_agents/hongkong/"
            "synthetic_households_tcs2022/synthetic_households.parquet"
        ),
        "fixed_link_grid": (
            input_root
            / "data/worldcommuting_od/hongkong/custom_features/"
            "hong_kong_fixed_link_grid/CityAndRegionSplit/"
            "hong_kong_fixed_link_grid/regions.shp"
        ),
    }
    missing = [key for key, path in result.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical energy inputs: {missing}"
        )
    return result


def canonical_hashes(paths: dict[str, Path]) -> dict[str, str]:
    result = {}
    for key, path in paths.items():
        if key == "fixed_link_grid":
            sidecars = [
                candidate
                for candidate in path.parent.glob(f"{path.stem}.*")
                if candidate.is_file()
            ]
            result["fixed_link_grid_bundle"] = sha256_bundle(sidecars)
        else:
            result[key] = sha256_file(path)
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
    for key, path in INPUT_DOCS.items():
        result[f"document:{key}"] = path
    return result


def hash_map(paths: dict[str, Path]) -> dict[str, str]:
    return {
        key: sha256_file(path)
        for key, path in sorted(paths.items())
    }


def source_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(
        SOURCE_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    records = {
        str(row["source_id"]): row for row in manifest["sources"]
    }
    wanted = {
        "consumer_oil_price": SOURCE_FILES["oil"],
        "government_private_car_energy_consumption": (
            SOURCE_FILES["consumption"]
        ),
        "government_electricity_tariff_2026": SOURCE_FILES["tariff"],
        "td_vehicle_fuel_type_2025_12": SOURCE_FILES["fleet"],
    }
    for source_id, path in wanted.items():
        record = records[source_id]
        expected_path = CAR_COST_ROOT / str(record["source_file"])
        if expected_path != path:
            raise RuntimeError(
                f"Manifest source path mismatch for {source_id}"
            )
        if sha256_file(path) != record["file_sha256"]:
            raise RuntimeError(
                f"Source snapshot hash mismatch for {source_id}"
            )
        if path.stat().st_size != int(record["file_size_bytes"]):
            raise RuntimeError(
                f"Source snapshot size mismatch for {source_id}"
            )
    return manifest, records


def read_fleet_counts(path: Path) -> dict[str, float]:
    raw = pd.read_excel(path, header=None, dtype=object)
    text = raw.astype(str).apply(
        lambda row: " | ".join(row.tolist()), axis=1
    )
    candidates = text[
        text.str.contains("Private Cars", case=False, na=False)
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one Private Cars row in TD table 4.4"
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
        raise RuntimeError("TD table 4.4 private-car row is incomplete")
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


def read_oil_prices(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"var\s+barChartData\s*=\s*(\{.*?\});",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Consumer Council price JSON not found")
    data = json.loads(match.group(1))["light"]["datasets"]
    walk = next(
        item["data"]
        for item in data
        if item["label"].startswith(
            "After walkin discount of regular-unleaded-gasoline"
        )
    )
    reductions = next(
        item["data"]
        for item in data
        if item["label"].startswith(
            "Walkin Reduce of regular-unleaded-gasoline"
        )
    )
    walk_prices = [float(value) for value in walk]
    pump_prices = [
        float(net) + float(reduction)
        for net, reduction in zip(walk, reductions, strict=True)
    ]
    updated = re.search(
        r"Updated at\s+([^<]+)",
        text,
    )
    if updated is None:
        raise RuntimeError("Consumer Council observation time not found")
    return {
        "low": min(walk_prices),
        "base": float(np.median(walk_prices)),
        "high": max(pump_prices),
        "walk_in_prices": walk_prices,
        "pump_prices": pump_prices,
        "observation_text": updated.group(1).strip(),
    }


def read_electricity_tariffs(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8")
    clp = re.search(
        r"140\.6 cents per kWh",
        text,
        flags=re.IGNORECASE,
    )
    hke = re.search(
        r"163\.3 cents per kWh",
        text,
        flags=re.IGNORECASE,
    )
    effective = re.search(
        r"with effect from January 1, 2026",
        text,
        flags=re.IGNORECASE,
    )
    if clp is None or hke is None or effective is None:
        raise RuntimeError("Official 2026 electricity tariffs not found")
    clp_customers = 2_900_000
    hke_customers = 600_000
    clp_rate = 1.406
    hke_rate = 1.633
    weighted = (
        clp_rate * clp_customers + hke_rate * hke_customers
    ) / (clp_customers + hke_customers)
    return {
        "low": clp_rate,
        "base": weighted,
        "high": hke_rate,
        "clp_customer_weight": clp_customers,
        "hke_customer_weight": hke_customers,
    }


def read_consumption(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8")
    petrol = re.search(
        r"about\s+11\.6 litres per 100 km",
        text,
        flags=re.IGNORECASE,
    )
    electric = re.search(
        r"about\s+0\.2 kWh per km",
        text,
        flags=re.IGNORECASE,
    )
    if petrol is None or electric is None:
        raise RuntimeError("Government energy consumption values absent")
    return {
        "petrol_base_l_per_100km": 11.6,
        "electric_base_kwh_per_100km": 20.0,
    }


def repository_source_path(record: dict[str, Any]) -> str:
    return (
        CAR_COST_ROOT / str(record["source_file"])
    ).as_posix()


def build_parameters(
    records: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    fleet = read_fleet_counts(SOURCE_FILES["fleet"])
    oil = read_oil_prices(SOURCE_FILES["oil"])
    tariffs = read_electricity_tariffs(SOURCE_FILES["tariff"])
    consumption = read_consumption(SOURCE_FILES["consumption"])
    petrol_consumption = {
        "low": consumption["petrol_base_l_per_100km"] * 0.8,
        "base": consumption["petrol_base_l_per_100km"],
        "high": consumption["petrol_base_l_per_100km"] * 1.2,
    }
    electric_consumption = {
        "low": consumption["electric_base_kwh_per_100km"] * 0.8,
        "base": consumption["electric_base_kwh_per_100km"],
        "high": consumption["electric_base_kwh_per_100km"] * 1.2,
    }
    price_basis = {
        "low": "minimum_standard_petrol_walk_in_price",
        "base": "median_standard_petrol_walk_in_price",
        "high": "maximum_listed_standard_petrol_pump_price",
    }
    tariff_basis = {
        "low": "clp_2026_average_net_tariff",
        "base": (
            "rounded_customer_count_weighted_clp_and_hk_electric_"
            "2026_average_net_tariff"
        ),
        "high": "hk_electric_2026_average_net_tariff",
    }
    sensitivity_factor = {"low": 0.8, "base": 1.0, "high": 1.2}
    source_ids = [
        "consumer_oil_price",
        "government_private_car_energy_consumption",
        "government_electricity_tariff_2026",
        "td_vehicle_fuel_type_2025_12",
    ]
    source_urls = "|".join(
        str(records[source_id]["source_url"])
        for source_id in source_ids
    )
    source_files = "|".join(
        repository_source_path(records[source_id])
        for source_id in source_ids
    )
    source_hashes = "|".join(
        str(records[source_id]["file_sha256"])
        for source_id in source_ids
    )
    rows = []
    for scenario in SCENARIOS:
        combustion_cost = (
            oil[scenario] * petrol_consumption[scenario] / 100.0
        )
        electric_cost = (
            tariffs[scenario]
            * electric_consumption[scenario]
            / 100.0
        )
        combustion_weighted = (
            fleet["combustion_proxy_share"] * combustion_cost
        )
        electric_weighted = fleet["electric_share"] * electric_cost
        fleet_cost = combustion_weighted + electric_weighted
        rows.append(
            {
                "scenario": scenario,
                "vehicle_powertrain": POWERTRAIN_PROXY,
                "individual_powertrain_available": False,
                "individual_powertrain_identifiable_leg_count": 0,
                "individual_powertrain_identifiable_fraction": 0.0,
                "proxy_assignment_scope": PROXY_ASSIGNMENT_SCOPE,
                "per_vehicle_powertrain_claimed": False,
                "petrol_price_hkd_per_litre": oil[scenario],
                "petrol_price_statistic": price_basis[scenario],
                "electricity_price_hkd_per_kwh": tariffs[scenario],
                "electricity_tariff_basis": tariff_basis[scenario],
                "fuel_consumption_l_per_100km": (
                    petrol_consumption[scenario]
                ),
                "electricity_consumption_kwh_per_100km": (
                    electric_consumption[scenario]
                ),
                "consumption_sensitivity_factor": (
                    sensitivity_factor[scenario]
                ),
                "consumption_sensitivity_status": (
                    "analyst_plus_or_minus_20_percent_sensitivity_"
                    "not_official_observed_distribution"
                ),
                "combustion_proxy_share": (
                    fleet["combustion_proxy_share"]
                ),
                "electric_share": fleet["electric_share"],
                "licensed_petrol": fleet["licensed_petrol"],
                "licensed_diesel": fleet["licensed_diesel"],
                "licensed_electric": fleet["licensed_electric"],
                "licensed_lpg": fleet["licensed_lpg"],
                "licensed_hydrogen": fleet["licensed_hydrogen"],
                "licensed_others": fleet["licensed_others"],
                "licensed_total": fleet["licensed_total"],
                "combustion_cost_hkd_per_km": combustion_cost,
                "electric_cost_hkd_per_km": electric_cost,
                "fleet_weighted_combustion_contribution_hkd_per_km": (
                    combustion_weighted
                ),
                "fleet_weighted_electric_contribution_hkd_per_km": (
                    electric_weighted
                ),
                "energy_cost_hkd_per_km": fleet_cost,
                "petrol_price_observation_date": (
                    "2026-07-28T10:47:00+08:00"
                ),
                "electricity_tariff_effective_period": (
                    "2026-01-01/2026-12-31"
                ),
                "fleet_composition_reference_date": "2025-12-31",
                "energy_consumption_source_publication_date": (
                    "2020-05-06"
                ),
                "source_snapshot_date": "2026-07-28",
                "scenario_assumption_date_status": (
                    "joint_price_and_consumption_scenario_envelope_"
                    "defined_2026-07-28_not_probability_interval"
                ),
                "cost_effective_date": "2026-07-28",
                "cost_effective_date_semantics": (
                    "price_candidate_reference_date_not_a_claim_that_"
                    "all_component_sources_took_effect_on_that_date"
                ),
                "clp_customer_weight": tariffs[
                    "clp_customer_weight"
                ],
                "hk_electric_customer_weight": tariffs[
                    "hke_customer_weight"
                ],
                "base_tariff_weight_formula": (
                    "(1.406*2900000+1.633*600000)/3500000"
                ),
                "customer_weight_quality": (
                    "rounded_official_2025_customer_account_counts_"
                    "for_spatial_tariff_weighting"
                ),
                "customer_weight_source_url": (
                    CLP_CUSTOMER_REFERENCE_URL
                    + "|"
                    + HKE_CUSTOMER_REFERENCE_URL
                ),
                "customer_weight_source_file": "",
                "customer_weight_source_snapshot_status": (
                    "supporting_official_web_references_not_part_of_"
                    "the_frozen_source_snapshot_manifest"
                ),
                "source_url": source_urls,
                "source_file": source_files,
                "file_sha256": source_hashes,
                "cost_quality": COST_QUALITY,
                "combustion_proxy_semantics": (
                    "petrol_diesel_and_other_non_electric_are_"
                    "aggregated_as_non_electric_combustion_proxy;"
                    "diesel_and_other_are_not_identified_as_petrol;"
                    "petrol_cost_is_a_temporary_proxy_due_to_missing_"
                    "individual_attributes_and_separate_diesel_inputs"
                ),
            }
        )
    frame = pd.DataFrame(rows)
    diagnostics = {
        "fleet": fleet,
        "oil": oil,
        "tariffs": tariffs,
        "consumption": consumption,
    }
    return frame, diagnostics


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


def reconstruct_links(route: Any | None) -> list[str]:
    if route is None:
        return []
    start = normalized_text(route.attrib.get("start_link"))
    end = normalized_text(route.attrib.get("end_link"))
    intermediate = (route.text or "").split()
    if intermediate and intermediate[0] == start:
        intermediate = intermediate[1:]
    if intermediate and intermediate[-1] == end:
        intermediate = intermediate[:-1]
    full = [start] if start else []
    full.extend(intermediate)
    if end and (not full or full[-1] != end):
        full.append(end)
    return full


def car_legs_in_plan(plan: Any) -> list[tuple[int, Any]]:
    main_activity_index = -1
    result = []
    for child in plan:
        name = tag_name(child)
        if name == "activity":
            if not child.attrib.get("type", "").endswith(
                "interaction"
            ):
                main_activity_index += 1
        elif name == "leg" and child.attrib.get("mode") == "car":
            result.append((main_activity_index, child))
    return result


def load_network(path: Path) -> dict[str, dict[str, Any]]:
    links: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "link":
                link_id = str(element.attrib["id"])
                if link_id in links:
                    raise RuntimeError(
                        f"Duplicate network link: {link_id}"
                    )
                links[link_id] = {
                    "from": str(element.attrib["from"]),
                    "to": str(element.attrib["to"]),
                    "length": float(element.attrib["length"]),
                }
            element.clear()
    return links


def load_vehicle_classes(path: Path) -> dict[str, str]:
    vehicles: dict[str, str] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "vehicle":
                vehicle_id = normalized_text(element.attrib.get("id"))
                vehicles[vehicle_id] = normalized_text(
                    element.attrib.get("type")
                )
            element.clear()
    return vehicles


def zero_distance_classification(
    distance: float,
    route_links: list[str],
    all_links_exist: bool,
    topology_contiguous: bool,
    convention_expected_m: float,
) -> str:
    if not finite(distance) or distance != 0:
        return "not_zero_distance"
    if (
        all_links_exist
        and topology_contiguous
        and len(route_links) == 1
        and route_links[0]
        and abs(convention_expected_m) <= DISTANCE_TOLERANCE_M
    ):
        return "valid_same_link_or_same_location_zero_distance"
    if (
        len(route_links) > 1
        or (
            finite(convention_expected_m)
            and convention_expected_m > DISTANCE_TOLERANCE_M
        )
    ):
        return "inconsistent_zero_distance_nontrivial_route"
    return "unresolved_zero_distance_reason"


def parse_routes(
    path: Path,
    needed_keys: set[tuple[str, int]],
    links: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    with gzip.open(path, "rb") as handle:
        context = etree.iterparse(
            handle, events=("end",), tag="person", huge_tree=True
        )
        for _, person in context:
            person_id = normalized_text(person.attrib.get("id"))
            plan = selected_plan(person)
            if plan is not None:
                for sequence, leg in car_legs_in_plan(plan):
                    key = (person_id, int(sequence))
                    if key not in needed_keys:
                        continue
                    if key in seen:
                        raise RuntimeError(
                            f"Duplicate routed car leg: {key}"
                        )
                    seen.add(key)
                    route = next(
                        (
                            child
                            for child in leg
                            if tag_name(child) == "route"
                        ),
                        None,
                    )
                    route_links = reconstruct_links(route)
                    all_links_exist = bool(route_links) and all(
                        link_id in links for link_id in route_links
                    )
                    topology = bool(route_links) and all_links_exist and all(
                        links[left]["to"] == links[right]["from"]
                        for left, right in zip(
                            route_links,
                            route_links[1:],
                            strict=False,
                        )
                    )
                    link_sum = (
                        float(
                            sum(
                                links[link_id]["length"]
                                for link_id in route_links
                            )
                        )
                        if all_links_exist
                        else float("nan")
                    )
                    start_length = (
                        float(links[route_links[0]]["length"])
                        if all_links_exist
                        else float("nan")
                    )
                    expected = (
                        link_sum - start_length
                        if finite(link_sum) and finite(start_length)
                        else float("nan")
                    )
                    distance = (
                        float(route.attrib["distance"])
                        if route is not None
                        and finite(route.attrib.get("distance"))
                        else float("nan")
                    )
                    raw_diff = (
                        distance - link_sum
                        if finite(distance) and finite(link_sum)
                        else float("nan")
                    )
                    convention_diff = (
                        distance - expected
                        if finite(distance) and finite(expected)
                        else float("nan")
                    )
                    relative = (
                        raw_diff / link_sum
                        if finite(raw_diff)
                        and finite(link_sum)
                        and link_sum > 0
                        else float("nan")
                    )
                    zero_class = zero_distance_classification(
                        distance,
                        route_links,
                        all_links_exist,
                        topology,
                        expected,
                    )
                    if not finite(distance) or distance < 0:
                        distance_quality = (
                            "unresolved_invalid_canonical_route_distance"
                        )
                    elif zero_class == (
                        "valid_same_link_or_same_location_zero_distance"
                    ):
                        distance_quality = (
                            "canonical_matsim_zero_distance_single_"
                            "same_link_no_interior_links"
                        )
                    elif abs(convention_diff) <= DISTANCE_TOLERANCE_M:
                        distance_quality = (
                            "canonical_matsim_route_distance_matches_"
                            "complete_sequence_minus_start_link"
                        )
                    else:
                        distance_quality = (
                            "canonical_route_distance_convention_"
                            "mismatch_review"
                        )
                    rows.append(
                        {
                            "person_id": person_id,
                            "leg_sequence": int(sequence),
                            "vehicle_ref_id": (
                                normalized_text(
                                    route.attrib.get("vehicleRefId")
                                )
                                if route is not None
                                else ""
                            ),
                            "mode": "car",
                            "route_distance_m": distance,
                            "route_distance_quality": distance_quality,
                            "route_start_link_id": (
                                route_links[0] if route_links else ""
                            ),
                            "route_end_link_id": (
                                route_links[-1] if route_links else ""
                            ),
                            "route_link_count": len(route_links),
                            "route_interior_link_count": max(
                                0, len(route_links) - 2
                            ),
                            "complete_link_sequence_length_m": link_sum,
                            "matsim_distance_convention_expected_m": (
                                expected
                            ),
                            "route_minus_link_sequence_distance_m": (
                                raw_diff
                            ),
                            "route_minus_convention_expected_m": (
                                convention_diff
                            ),
                            "route_minus_link_sequence_relative": relative,
                            "all_route_links_exist": all_links_exist,
                            "route_topology_contiguous": topology,
                            "zero_distance_classification": zero_class,
                        }
                    )
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]
    if seen != needed_keys:
        raise RuntimeError(
            "Routed car keys differ from manifest car keys: "
            f"missing={len(needed_keys - seen)}, "
            f"extra={len(seen - needed_keys)}"
        )
    return pd.DataFrame(rows)


def status_for_leg(row: Any) -> tuple[str, str]:
    if row.vehicle_class == "motorcycle":
        return "out_of_scope_motorcycle", "vehicle_class_motorcycle"
    if row.vehicle_class != "private_car":
        return "unresolved_vehicle_class", "unknown_vehicle_class"
    if not finite(row.route_distance_m) or row.route_distance_m < 0:
        return (
            "unresolved_route_distance",
            "missing_or_negative_canonical_route_distance",
        )
    if row.zero_distance_classification == (
        "valid_same_link_or_same_location_zero_distance"
    ):
        return "resolved_zero_distance_energy_zero", ""
    if row.zero_distance_classification == (
        "inconsistent_zero_distance_nontrivial_route"
    ):
        return (
            "unresolved_zero_distance_inconsistent_route",
            "zero_distance_with_nontrivial_positive_length_route",
        )
    if row.zero_distance_classification == (
        "unresolved_zero_distance_reason"
    ):
        return (
            "unresolved_route_distance",
            "zero_distance_reason_not_supported",
        )
    if row.route_distance_quality.endswith("mismatch_review"):
        return (
            "unresolved_route_distance",
            "canonical_distance_does_not_match_audited_route_convention",
        )
    return "resolved_representative_fleet_average", ""


def apply_scenario(
    legs: pd.DataFrame,
    parameter: Any,
    scenario: str,
) -> pd.DataFrame:
    rows = []
    for row in legs.itertuples(index=False):
        status, reason = status_for_leg(row)
        is_private = row.vehicle_class == "private_car"
        resolved = status.startswith("resolved_")
        distance_km = (
            float(row.route_distance_m) / 1000.0
            if resolved
            else float("nan")
        )
        if is_private:
            powertrain = POWERTRAIN_PROXY
            combustion_share = float(parameter.combustion_proxy_share)
            electric_share = float(parameter.electric_share)
            combustion_cost = float(
                parameter.combustion_cost_hkd_per_km
            )
            electric_cost = float(
                parameter.electric_cost_hkd_per_km
            )
            energy_cost = float(parameter.energy_cost_hkd_per_km)
            weighted_combustion_per_km = float(
                parameter
                .fleet_weighted_combustion_contribution_hkd_per_km
            )
            weighted_electric_per_km = float(
                parameter
                .fleet_weighted_electric_contribution_hkd_per_km
            )
        else:
            powertrain = ""
            combustion_share = float("nan")
            electric_share = float("nan")
            combustion_cost = float("nan")
            electric_cost = float("nan")
            energy_cost = float("nan")
            weighted_combustion_per_km = float("nan")
            weighted_electric_per_km = float("nan")
        combustion_contribution = (
            distance_km * weighted_combustion_per_km
            if resolved
            else float("nan")
        )
        electric_contribution = (
            distance_km * weighted_electric_per_km
            if resolved
            else float("nan")
        )
        cost = (
            combustion_contribution + electric_contribution
            if resolved
            else float("nan")
        )
        rows.append(
            {
                "person_id": row.person_id,
                "leg_sequence": int(row.leg_sequence),
                "vehicle_ref_id": row.vehicle_ref_id,
                "vehicle_class": row.vehicle_class,
                "mode": "car",
                "route_distance_m": row.route_distance_m,
                "route_distance_quality": row.route_distance_quality,
                "route_start_link_id": row.route_start_link_id,
                "route_end_link_id": row.route_end_link_id,
                "route_link_count": int(row.route_link_count),
                "route_interior_link_count": int(
                    row.route_interior_link_count
                ),
                "complete_link_sequence_length_m": (
                    row.complete_link_sequence_length_m
                ),
                "matsim_distance_convention_expected_m": (
                    row.matsim_distance_convention_expected_m
                ),
                "route_minus_link_sequence_distance_m": (
                    row.route_minus_link_sequence_distance_m
                ),
                "route_minus_convention_expected_m": (
                    row.route_minus_convention_expected_m
                ),
                "route_minus_link_sequence_relative": (
                    row.route_minus_link_sequence_relative
                ),
                "manifest_distance_field_available": False,
                "manifest_route_distance_m": float("nan"),
                "manifest_route_distance_difference_m": float("nan"),
                "zero_distance_classification": (
                    row.zero_distance_classification
                ),
                "vehicle_powertrain": powertrain,
                "individual_powertrain_observed": False,
                "combustion_proxy_share": combustion_share,
                "electric_share": electric_share,
                "combustion_cost_hkd_per_km": combustion_cost,
                "electric_cost_hkd_per_km": electric_cost,
                "energy_cost_hkd_per_km": energy_cost,
                "fleet_weighted_combustion_contribution_hkd_per_km": (
                    weighted_combustion_per_km
                ),
                "fleet_weighted_electric_contribution_hkd_per_km": (
                    weighted_electric_per_km
                ),
                "fleet_weighted_combustion_contribution_hkd": (
                    combustion_contribution
                ),
                "fleet_weighted_electric_contribution_hkd": (
                    electric_contribution
                ),
                "cost_component": "fuel_or_electricity",
                "cost_hkd": cost,
                "cost_source": (
                    (
                        DEFAULT_OUTPUT
                        / "energy_parameters_repository_relative.csv"
                    ).as_posix()
                    if is_private
                    else ""
                ),
                "cost_effective_date": (
                    str(parameter.cost_effective_date)
                    if is_private
                    else ""
                ),
                "cost_quality": (
                    COST_QUALITY if is_private else "out_of_scope"
                ),
                "scenario": scenario,
                "energy_status": status,
                "unresolved_reason": reason,
            }
        )
    result = pd.DataFrame(rows)[OUTPUT_COLUMNS]
    return result.sort_values(
        ["person_id", "leg_sequence"]
    ).reset_index(drop=True)


def distance_band(value: object) -> str:
    if not finite(value):
        return "unavailable"
    distance_km = float(value) / 1000.0
    if distance_km == 0:
        return "00_zero"
    if distance_km <= 1:
        return "01_0_to_1km"
    if distance_km <= 5:
        return "02_1_to_5km"
    if distance_km <= 10:
        return "03_5_to_10km"
    if distance_km <= 20:
        return "04_10_to_20km"
    if distance_km <= 40:
        return "05_20_to_40km"
    return "06_over_40km"


def summary_rows(
    frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []
    for scenario, frame in frames.items():
        working = frame.copy()
        working["distance_band"] = working["route_distance_m"].map(
            distance_band
        )
        dimensions = {
            "overall": pd.Series(
                ["all_records"] * len(working),
                index=working.index,
            ),
            "energy_status": working["energy_status"],
            "route_distance_quality": working[
                "route_distance_quality"
            ],
            "zero_distance_classification": working[
                "zero_distance_classification"
            ],
            "distance_band": working["distance_band"],
        }
        for dimension, values in dimensions.items():
            for value, group in working.groupby(
                values, dropna=False, sort=True
            ):
                resolved = group["energy_status"].str.startswith(
                    "resolved_"
                )
                unresolved = group["energy_status"].str.startswith(
                    "unresolved_"
                )
                out = group["energy_status"].str.startswith(
                    "out_of_scope_"
                )
                costs = group.loc[resolved, "cost_hkd"].dropna()
                rows.append(
                    {
                        "scenario": scenario,
                        "summary_dimension": dimension,
                        "summary_value": str(value),
                        "record_count": int(len(group)),
                        "resolved_count": int(resolved.sum()),
                        "unresolved_count": int(unresolved.sum()),
                        "out_of_scope_count": int(out.sum()),
                        "total_cost_hkd_resolved_only": (
                            float(costs.sum())
                            if len(costs)
                            else float("nan")
                        ),
                        "mean_cost_hkd_resolved_only": (
                            float(costs.mean())
                            if len(costs)
                            else float("nan")
                        ),
                        "median_cost_hkd_resolved_only": (
                            float(costs.median())
                            if len(costs)
                            else float("nan")
                        ),
                        "p90_cost_hkd_resolved_only": (
                            float(costs.quantile(0.9))
                            if len(costs)
                            else float("nan")
                        ),
                    }
                )
    return pd.DataFrame(rows)


def quantiles(series: pd.Series) -> dict[str, float]:
    valid = series.dropna()
    return {
        "min": float(valid.min()),
        "p10": float(valid.quantile(0.1)),
        "median": float(valid.median()),
        "p90": float(valid.quantile(0.9)),
        "p99": float(valid.quantile(0.99)),
        "max": float(valid.max()),
    }


def compare_old_parameters(
    parameters: pd.DataFrame,
) -> dict[str, float]:
    old = pd.read_csv(OLD_PARAMETERS_PATH).set_index("scenario")
    new = parameters.set_index("scenario")
    columns = [
        "petrol_price_hkd_per_litre",
        "electricity_price_hkd_per_kwh",
        "fuel_consumption_l_per_100km",
        "electricity_consumption_kwh_per_100km",
        "combustion_proxy_share",
        "electric_share",
        "energy_cost_hkd_per_km",
    ]
    return {
        column: float(
            (old.loc[list(SCENARIOS), column]
             - new.loc[list(SCENARIOS), column]).abs().max()
        )
        for column in columns
    }


def validate(
    legs: pd.DataFrame,
    parameters: pd.DataFrame,
    parameter_diagnostics: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    feasibility: pd.DataFrame,
) -> dict[str, Any]:
    private = legs.loc[legs["vehicle_class"].eq("private_car")]
    motorcycle = legs.loc[legs["vehicle_class"].eq("motorcycle")]
    unknown = legs.loc[
        ~legs["vehicle_class"].isin(["private_car", "motorcycle"])
    ]
    distance = legs["route_distance_m"]
    private_zero = private.loc[private["route_distance_m"].eq(0)]
    raw_difference = legs[
        "route_minus_link_sequence_distance_m"
    ]
    relative_difference = legs[
        "route_minus_link_sequence_relative"
    ]
    convention_residual = legs[
        "route_minus_convention_expected_m"
    ]
    scenario_results: dict[str, Any] = {}
    formula_errors: dict[str, float] = {}
    monotonic: dict[str, bool] = {}
    status_counts: dict[str, dict[str, int]] = {}
    resolved_counts: dict[str, int] = {}
    unresolved_counts: dict[str, int] = {}
    out_counts: dict[str, int] = {}
    totals: dict[str, float] = {}
    statistics: dict[str, dict[str, float]] = {}
    null_valid: dict[str, bool] = {}
    zero_valid: dict[str, bool] = {}
    for scenario, frame in frames.items():
        resolved = frame["energy_status"].str.startswith("resolved_")
        unresolved = frame["energy_status"].str.startswith(
            "unresolved_"
        )
        out = frame["energy_status"].str.startswith("out_of_scope_")
        expected = (
            frame["route_distance_m"]
            / 1000.0
            * frame["energy_cost_hkd_per_km"]
        )
        comparable = resolved & expected.notna()
        formula_errors[scenario] = float(
            (
                frame.loc[comparable, "cost_hkd"]
                - expected.loc[comparable]
            ).abs().max()
        )
        positive = frame.loc[
            resolved & frame["route_distance_m"].gt(0)
        ].sort_values("route_distance_m")
        monotonic[scenario] = bool(
            positive["cost_hkd"].diff().dropna().ge(
                -FLOAT_TOLERANCE
            ).all()
        )
        status_counts[scenario] = {
            str(key): int(value)
            for key, value in frame["energy_status"]
            .value_counts()
            .items()
        }
        resolved_counts[scenario] = int(resolved.sum())
        unresolved_counts[scenario] = int(unresolved.sum())
        out_counts[scenario] = int(out.sum())
        costs = frame.loc[resolved, "cost_hkd"]
        totals[scenario] = float(costs.sum())
        statistics[scenario] = {
            "mean": float(costs.mean()),
            "median": float(costs.median()),
            "p90": float(costs.quantile(0.9)),
        }
        null_valid[scenario] = bool(
            frame.loc[unresolved | out, "cost_hkd"].isna().all()
        )
        zero_rows = frame["cost_hkd"].eq(0)
        zero_valid[scenario] = bool(
            (
                ~zero_rows
                | frame["energy_status"].eq(
                    "resolved_zero_distance_energy_zero"
                )
            ).all()
        )
        scenario_results[scenario] = {
            "row_count": int(len(frame)),
            "person_leg_key_unique": bool(
                not frame.duplicated(
                    ["person_id", "leg_sequence"]
                ).any()
            ),
            "non_null_cost_non_negative": bool(
                frame["cost_hkd"].dropna().ge(0).all()
            ),
        }

    pivot = pd.concat(
        [
            frames[scenario][
                ["person_id", "leg_sequence", "cost_hkd"]
            ].rename(columns={"cost_hkd": scenario})
            for scenario in SCENARIOS
        ],
        axis=1,
    )
    complete = pivot[list(SCENARIOS)].notna().all(axis=1)
    order_valid = bool(
        (
            (
                pivot.loc[complete, "low"]
                <= pivot.loc[complete, "base"]
            )
            & (
                pivot.loc[complete, "base"]
                <= pivot.loc[complete, "high"]
            )
        ).all()
    )
    parameter_formula_errors = {}
    for row in parameters.itertuples(index=False):
        combustion = (
            row.petrol_price_hkd_per_litre
            * row.fuel_consumption_l_per_100km
            / 100.0
        )
        electric = (
            row.electricity_price_hkd_per_kwh
            * row.electricity_consumption_kwh_per_100km
            / 100.0
        )
        fleet_cost = (
            row.combustion_proxy_share * combustion
            + row.electric_share * electric
        )
        parameter_formula_errors[row.scenario] = {
            "combustion_cost_hkd_per_km_error": float(
                abs(combustion - row.combustion_cost_hkd_per_km)
            ),
            "electric_cost_hkd_per_km_error": float(
                abs(electric - row.electric_cost_hkd_per_km)
            ),
            "fleet_average_hkd_per_km_error": float(
                abs(fleet_cost - row.energy_cost_hkd_per_km)
            ),
        }
    feasibility_compare = legs.merge(
        feasibility[
            [
                "person_id",
                "leg_sequence",
                "route_distance_m",
                "network_distance_sum_m",
                "vehicle_class",
            ]
        ],
        on=["person_id", "leg_sequence"],
        how="left",
        suffixes=("_rebuilt", "_feasibility"),
        validate="one_to_one",
    )
    feasibility_route_error = float(
        (
            feasibility_compare["route_distance_m_rebuilt"]
            - feasibility_compare["route_distance_m_feasibility"]
        ).abs().max()
    )
    feasibility_link_error = float(
        (
            feasibility_compare["complete_link_sequence_length_m"]
            - feasibility_compare["network_distance_sum_m"]
        ).abs().max()
    )
    fleet = parameter_diagnostics["fleet"]
    share_sum_error = abs(
        fleet["combustion_proxy_share"]
        + fleet["electric_share"]
        - 1.0
    )
    old_parameter_errors = compare_old_parameters(parameters)
    parameter_error_max = max(
        value
        for errors in parameter_formula_errors.values()
        for value in errors.values()
    )
    publishable = bool(
        len(legs) == 67718
        and len(private) == 64789
        and len(motorcycle) == 2929
        and len(unknown) == 0
        and all(
            result["row_count"] == 67718
            and result["person_leg_key_unique"]
            and result["non_null_cost_non_negative"]
            for result in scenario_results.values()
        )
        and all(value == 0 for value in unresolved_counts.values())
        and all(value == 2929 for value in out_counts.values())
        and all(value == 64789 for value in resolved_counts.values())
        and all(value <= FLOAT_TOLERANCE for value in formula_errors.values())
        and parameter_error_max <= FLOAT_TOLERANCE
        and share_sum_error <= FLOAT_TOLERANCE
        and all(monotonic.values())
        and all(null_valid.values())
        and all(zero_valid.values())
        and order_valid
        and len(private_zero) == 33
        and private_zero["zero_distance_classification"].eq(
            "valid_same_link_or_same_location_zero_distance"
        ).all()
        and convention_residual.abs().max() <= DISTANCE_TOLERANCE_M
        and feasibility_route_error <= DISTANCE_TOLERANCE_M
        and feasibility_link_error <= DISTANCE_TOLERANCE_M
        and all(
            value <= FLOAT_TOLERANCE
            for value in old_parameter_errors.values()
        )
    )
    return {
        "audit": (
            "Hong Kong private-car representative-fleet "
            "fuel-or-electricity application v1"
        ),
        "source_commit": SOURCE_COMMIT,
        "candidate_output_only": True,
        "publishable_candidate": publishable,
        "blocked": not publishable,
        "matsim_scoring_modified": False,
        "unified_car_cost_modified": False,
        "toll_candidate_modified": False,
        "parking_candidate_modified": False,
        "fixed_vehicle_ownership_cost_included": False,
        "powertrain_semantics": {
            "individual_powertrain_available": False,
            "individual_powertrain_identifiable_leg_count": 0,
            "individual_powertrain_identifiable_fraction": 0.0,
            "vehicle_powertrain": POWERTRAIN_PROXY,
            "proxy_assignment_scope": PROXY_ASSIGNMENT_SCOPE,
            "per_vehicle_powertrain_claimed": False,
            "random_or_hash_powertrain_assignment_used": False,
            "combustion_proxy_definition": (
                "petrol_plus_diesel_plus_lpg_plus_hydrogen_plus_others"
            ),
            "diesel_or_other_claimed_as_identified_petrol": False,
        },
        "input_counts": {
            "car_legs": int(len(legs)),
            "private_car_legs": int(len(private)),
            "motorcycle_out_of_scope": int(len(motorcycle)),
            "unknown_vehicle_class": int(len(unknown)),
        },
        "route_distance_audit": {
            "unit": "m",
            "unit_basis": (
                "MATSim network and route distance in EPSG:32650 "
                "scenario metre convention"
            ),
            "all_car": {
                "present": int(distance.notna().sum()),
                "nan": int(distance.isna().sum()),
                "negative": int(distance.lt(0).sum()),
                "zero": int(distance.eq(0).sum()),
                "positive": int(distance.gt(0).sum()),
            },
            "private_car": {
                "present": int(
                    private["route_distance_m"].notna().sum()
                ),
                "nan": int(private["route_distance_m"].isna().sum()),
                "negative": int(
                    private["route_distance_m"].lt(0).sum()
                ),
                "zero": int(private["route_distance_m"].eq(0).sum()),
                "positive": int(
                    private["route_distance_m"].gt(0).sum()
                ),
            },
            "motorcycle": {
                "present": int(
                    motorcycle["route_distance_m"].notna().sum()
                ),
                "nan": int(
                    motorcycle["route_distance_m"].isna().sum()
                ),
                "negative": int(
                    motorcycle["route_distance_m"].lt(0).sum()
                ),
                "zero": int(
                    motorcycle["route_distance_m"].eq(0).sum()
                ),
                "positive": int(
                    motorcycle["route_distance_m"].gt(0).sum()
                ),
            },
            "private_car_zero_distance_classification": {
                str(key): int(value)
                for key, value in private_zero[
                    "zero_distance_classification"
                ].value_counts().items()
            },
            "zero_distance_evidence": {
                "all_33_route_link_count_one": bool(
                    private_zero["route_link_count"].eq(1).all()
                ),
                "all_33_start_end_same_link": bool(
                    private_zero["route_start_link_id"].eq(
                        private_zero["route_end_link_id"]
                    ).all()
                ),
                "all_33_no_interior_link": bool(
                    private_zero["route_interior_link_count"].eq(0).all()
                ),
                "all_33_complete_sequence_and_topology_valid": bool(
                    private_zero["all_route_links_exist"].all()
                    and private_zero[
                        "route_topology_contiguous"
                    ].all()
                ),
            },
            "route_minus_complete_link_sequence_m": quantiles(
                raw_difference
            ),
            "route_minus_complete_link_sequence_relative": quantiles(
                relative_difference
            ),
            "matsim_convention": (
                "route_distance_equals_complete_link_sequence_length_"
                "minus_start_link_length"
            ),
            "route_minus_convention_expected_max_abs_m": float(
                convention_residual.abs().max()
            ),
            "manifest_distance_field_available": False,
            "manifest_distance_comparison_status": (
                "not_available_manifest_has_no_distance_field"
            ),
            "canonical_route_distance_replaced": False,
            "feasibility_route_distance_max_abs_error_m": (
                feasibility_route_error
            ),
            "feasibility_link_sum_max_abs_error_m": (
                feasibility_link_error
            ),
        },
        "fleet_composition_recalculation": {
            **parameter_diagnostics["fleet"],
            "combustion_plus_electric_share_sum": float(
                fleet["combustion_proxy_share"]
                + fleet["electric_share"]
            ),
            "share_sum_error": float(share_sum_error),
            "electric_is_official_licensed_electric_private_car_share": (
                True
            ),
            "combustion_uses_petrol_cost_proxy_due_to_missing_inputs": (
                True
            ),
        },
        "source_parameter_recalculation": {
            "consumer_oil_price_walk_in_values_hkd_per_litre": (
                parameter_diagnostics["oil"]["walk_in_prices"]
            ),
            "consumer_oil_price_pump_values_hkd_per_litre": (
                parameter_diagnostics["oil"]["pump_prices"]
            ),
            "consumer_oil_observation_text": (
                parameter_diagnostics["oil"]["observation_text"]
            ),
            "electricity_customer_weight_formula": (
                "(1.406*2900000+1.633*600000)/3500000"
            ),
            "electricity_customer_weight_result_hkd_per_kwh": (
                parameter_diagnostics["tariffs"]["base"]
            ),
            "low_high_consumption_is_analyst_plus_minus_20_percent": (
                True
            ),
            "scenario_semantics": (
                "joint_price_and_consumption_scenario_envelope_"
                "not_statistical_confidence_interval"
            ),
            "parameter_formula_errors": parameter_formula_errors,
            "maximum_parameter_formula_error": float(
                parameter_error_max
            ),
            "old_parameter_table_recalculation_max_abs_errors": (
                old_parameter_errors
            ),
            "scenario_parameters": {
                str(row.scenario): {
                    "petrol_price_hkd_per_litre": float(
                        row.petrol_price_hkd_per_litre
                    ),
                    "electricity_price_hkd_per_kwh": float(
                        row.electricity_price_hkd_per_kwh
                    ),
                    "fuel_consumption_l_per_100km": float(
                        row.fuel_consumption_l_per_100km
                    ),
                    "electricity_consumption_kwh_per_100km": float(
                        row.electricity_consumption_kwh_per_100km
                    ),
                    "combustion_cost_hkd_per_km": float(
                        row.combustion_cost_hkd_per_km
                    ),
                    "electric_cost_hkd_per_km": float(
                        row.electric_cost_hkd_per_km
                    ),
                    "fleet_weighted_combustion_contribution_hkd_per_km": (
                        float(
                            row
                            .fleet_weighted_combustion_contribution_hkd_per_km
                        )
                    ),
                    "fleet_weighted_electric_contribution_hkd_per_km": (
                        float(
                            row
                            .fleet_weighted_electric_contribution_hkd_per_km
                        )
                    ),
                    "energy_cost_hkd_per_km": float(
                        row.energy_cost_hkd_per_km
                    ),
                }
                for row in parameters.itertuples(index=False)
            },
        },
        "scenario_outputs": {
            "basic_validation": scenario_results,
            "energy_status_counts": status_counts,
            "resolved_counts": resolved_counts,
            "unresolved_counts": unresolved_counts,
            "out_of_scope_counts": out_counts,
            "resolved_only_totals_hkd": totals,
            "resolved_only_statistics_hkd": statistics,
            "leg_formula_max_abs_error_hkd": formula_errors,
            "positive_distance_cost_monotonic": monotonic,
            "unresolved_and_out_of_scope_cost_null": null_valid,
            "only_validated_zero_distance_has_zero_cost": zero_valid,
            "non_null_low_le_base_le_high": order_valid,
        },
    }


def repairs(validation: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "repair_id": "ENERGY-R01",
                "severity": "medium",
                "component": "individual_powertrain",
                "finding": (
                    "No individual private-car powertrain, fuel type, "
                    "engine size, or age is present in canonical vehicles."
                ),
                "required_change": (
                    "Keep the representative licensed-fleet proxy until "
                    "a sourced vehicle-level attribute exists."
                ),
            },
            {
                "repair_id": "ENERGY-R02",
                "severity": "medium",
                "component": "combustion_proxy",
                "finding": (
                    "Diesel and other non-electric licensed cars are "
                    "included in a combustion proxy using petrol cost."
                ),
                "required_change": (
                    "Add separately sourced diesel/other price and "
                    "consumption only when the model can support those "
                    "classes; do not relabel them as observed petrol cars."
                ),
            },
            {
                "repair_id": "ENERGY-R03",
                "severity": "low",
                "component": "electricity_weight",
                "finding": (
                    "The base tariff uses rounded official 2025 customer "
                    "account counts of 2.9m CLP and 0.6m HK Electric."
                ),
                "required_change": (
                    "Pin the supporting official customer-account pages "
                    "if a future parameter refresh changes these weights."
                ),
            },
        ]
    )


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    canonical = canonical_paths(args.input_project_root.resolve())
    required = {
        **SOURCE_FILES,
        **INPUT_DOCS,
        **FEASIBILITY_INPUTS,
        "source_manifest": SOURCE_MANIFEST_PATH,
        "old_energy_parameters": OLD_PARAMETERS_PATH,
    }
    missing = [key for key, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing local energy inputs: {missing}"
        )
    protected = protected_paths(args.output_dir)
    protected_before = hash_map(protected)
    canonical_before = canonical_hashes(canonical)

    _, records = source_manifest()
    parameters, parameter_diagnostics = build_parameters(records)
    manifest = pd.read_parquet(canonical["trip_manifest"])
    if "route_distance_m" in manifest.columns:
        raise RuntimeError(
            "Manifest distance field appeared; implement explicit audit"
        )
    manifest_car = manifest.loc[manifest["mode"].eq("car")].copy()
    manifest_car["person_id"] = manifest_car["person_id"].astype(str)
    manifest_car["leg_sequence"] = manifest_car[
        "leg_sequence"
    ].astype(int)
    if manifest_car.duplicated(["person_id", "leg_sequence"]).any():
        raise RuntimeError("Duplicate car person-leg key in manifest")
    needed_keys = set(
        zip(
            manifest_car["person_id"],
            manifest_car["leg_sequence"],
            strict=False,
        )
    )
    network = load_network(canonical["network"])
    vehicles = load_vehicle_classes(canonical["private_vehicles"])
    legs = parse_routes(
        canonical["plans_routed"], needed_keys, network
    )
    legs["vehicle_class"] = legs["vehicle_ref_id"].map(
        vehicles
    ).fillna("unresolved")
    feasibility = pd.read_parquet(
        FEASIBILITY_INPUTS["feasibility_table"]
    )
    feasibility["person_id"] = feasibility["person_id"].astype(str)
    feasibility["leg_sequence"] = feasibility[
        "leg_sequence"
    ].astype(int)
    frames = {}
    parameter_index = parameters.set_index("scenario")
    for scenario in SCENARIOS:
        frames[scenario] = apply_scenario(
            legs,
            parameter_index.loc[scenario],
            scenario,
        )
    summary = summary_rows(frames)
    validation = validate(
        legs,
        parameters,
        parameter_diagnostics,
        frames,
        feasibility,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    parameters.to_csv(
        args.output_dir / "energy_parameters_repository_relative.csv",
        index=False,
        encoding="utf-8",
    )
    for scenario, frame in frames.items():
        frame.to_parquet(
            args.output_dir
            / f"car_leg_energy_cost_estimates_{scenario}.parquet",
            index=False,
        )
    summary.to_csv(
        args.output_dir / "energy_application_summary.csv",
        index=False,
        encoding="utf-8",
    )
    repairs(validation).to_csv(
        args.output_dir / "energy_application_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )

    protected_after = hash_map(protected)
    canonical_after = canonical_hashes(canonical)
    protected_unchanged = protected_before == protected_after
    canonical_unchanged = canonical_before == canonical_after
    validation["protected_inputs"] = {
        "all_existing_car_cost_files_unchanged": protected_unchanged,
        "toll_network_mapping_v1_unchanged": all(
            protected_before[key] == protected_after[key]
            for key in protected_before
            if "toll_network_mapping_v1" in key
        ),
        "toll_rate_application_v1_unchanged": all(
            protected_before[key] == protected_after[key]
            for key in protected_before
            if "toll_rate_application_v1" in key
        ),
        "parking_event_application_v1_unchanged": all(
            protected_before[key] == protected_after[key]
            for key in protected_before
            if "parking_event_application_v1" in key
        ),
        "canonical_inputs_unchanged": canonical_unchanged,
        "all_protected_sha256_unchanged": bool(
            protected_unchanged and canonical_unchanged
        ),
    }
    if not (
        validation["protected_inputs"]["all_protected_sha256_unchanged"]
    ):
        validation["publishable_candidate"] = False
        validation["blocked"] = True
    hashes = {
        "input_root_role": (
            "canonical_project_read_only_large_inputs;"
            "absolute_root_omitted"
        ),
        "source_commit": SOURCE_COMMIT,
        "canonical_role_paths": {
            key: (
                path.relative_to(args.input_project_root.resolve())
                .as_posix()
            )
            for key, path in canonical.items()
        },
        "canonical_hashes_before": canonical_before,
        "canonical_hashes_after": canonical_after,
        "existing_car_cost_hashes_before": protected_before,
        "existing_car_cost_hashes_after": protected_after,
        "source_snapshot_manifest_checks": {
            source_id: {
                "source_path": repository_source_path(records[source_id]),
                "manifest_sha256": records[source_id]["file_sha256"],
                "actual_sha256": sha256_file(
                    CAR_COST_ROOT
                    / str(records[source_id]["source_file"])
                ),
                "matches": True,
            }
            for source_id in [
                "consumer_oil_price",
                "government_private_car_energy_consumption",
                "government_electricity_tariff_2026",
                "td_vehicle_fuel_type_2025_12",
            ]
        },
        "customer_weight_supporting_official_urls": {
            "clp": CLP_CUSTOMER_REFERENCE_URL,
            "hk_electric": HKE_CUSTOMER_REFERENCE_URL,
            "local_snapshot_status": (
                "not_part_of_frozen_source_snapshot_manifest"
            ),
        },
        "all_protected_sha256_unchanged": bool(
            protected_unchanged and canonical_unchanged
        ),
    }
    write_json(
        args.output_dir / "energy_application_validation.json",
        validation,
    )
    write_json(
        args.output_dir / "energy_application_input_hashes.json",
        hashes,
    )
    if validation["blocked"]:
        raise RuntimeError(
            "Energy candidate failed a hard-stop validation"
        )
    print(
        json.dumps(
            {
                "output_dir": args.output_dir.as_posix(),
                "publishable_candidate": True,
                "private_car_legs": validation["input_counts"][
                    "private_car_legs"
                ],
                "motorcycle_out_of_scope": validation["input_counts"][
                    "motorcycle_out_of_scope"
                ],
                "zero_distance_private_car": validation[
                    "route_distance_audit"
                ]["private_car"]["zero"],
                "resolved_only_totals_hkd": validation[
                    "scenario_outputs"
                ]["resolved_only_totals_hkd"],
                "formula_max_abs_error_hkd": validation[
                    "scenario_outputs"
                ]["leg_formula_max_abs_error_hkd"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
