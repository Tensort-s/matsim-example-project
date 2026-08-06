#!/usr/bin/env python3
"""Build the Hong Kong 44,000-Taxi population with no ``ride`` mode.

The transformation starts from the routed native-Taxi population and writes a
new, never-overwritten pre-routing population.  It preserves the 2,490 student
private-vehicle legs by exchanging people, not totals: 956 no-car students are
paired with 956 car-household students currently using PT or walk.  The
donors become ``car_passenger`` and the displaced students inherit each
donor's PT/walk mode.  Exactly 122 complete fixed-worker tours (244 legs) are
also retained as ``car_passenger``.  School bus remains student-only, every
remaining point-to-point passenger leg becomes Taxi, and ``ride`` disappears.

Only the 3,824 student exchange legs have their old routes cleared.  A later
MATSim route-only pass must rebuild those trips before simulation.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lxml import etree as ET


ROOT = Path(__file__).resolve().parents[3]
COSTS_DIR = ROOT / "scripts/hong_kong_single_city/costs"
if str(COSTS_DIR) not in sys.path:
    sys.path.insert(0, str(COSTS_DIR))

from estimate_hong_kong_taxi_leg_fares import (  # noqa: E402
    assign_taxi_type,
    fare_for_distance,
    merge_facility_evidence,
)


SELECTION_SEED = 20260805
TARGET_TAXI_LEGS = 44_000
TARGET_CAR_PASSENGER_LEGS = 2_734
TARGET_STUDENT_CAR_PASSENGER_LEGS = 2_490
TARGET_ADULT_CAR_PASSENGER_LEGS = 244
TARGET_SCHOOL_BUS_LEGS = 9_626
TARGET_PASSENGER_POOL_LEGS = 56_360
TARGET_STUDENT_SWAP_PERSONS = 956
PHYSICAL_TRANSIT_MODES = "bus,gmb,train,light_rail,ferry"
FROZEN_INNOVATION_STRATEGIES = {
    "ReRoute", "SubtourModeChoice", "TimeAllocationMutator"
}

TAXI_ATTRIBUTE_CLASSES = {
    "hkTaxiFareBaselineHkd": "java.lang.Double",
    "hkTaxiType": "java.lang.String",
    "hkTaxiFareScope": "java.lang.String",
    "hkTaxiFareModelVersion": "java.lang.String",
    "hkTaxiClassificationSource": "java.lang.String",
    "hkTaxiMainTripIndex": "java.lang.Integer",
}
TAXI_STATIC_VALUES = {
    "hkTaxiFareScope": "distance_only_v1",
    "hkTaxiFareModelVersion": "hong_kong_taxi_fare_model_v1",
}
FINAL_MODE_COUNTS = {
    "car": 67_718,
    "car_passenger": TARGET_CAR_PASSENGER_LEGS,
    "pt": 557_104,
    "school_bus": TARGET_SCHOOL_BUS_LEGS,
    "taxi": TARGET_TAXI_LEGS,
    "walk": 197_868,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matsim-root", type=Path, required=True)
    parser.add_argument("--input-plans", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output-preroute-plans", type=Path, required=True)
    parser.add_argument("--output-route-config", type=Path, required=True)
    parser.add_argument("--output-final-config", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument(
        "--runtime-preroute-plans-path",
        required=True,
        help="Plans path written to the local/remote route-only config.",
    )
    parser.add_argument(
        "--runtime-final-plans-path",
        required=True,
        help="Plans path written to the final Stage 11 config.",
    )
    parser.add_argument(
        "--route-output-directory",
        required=True,
        help="New MATSim controller output directory for route preparation.",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    raise RuntimeError(message)


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def direct_children(element: ET._Element, name: str) -> list[ET._Element]:
    return [child for child in element if local_name(child) == name]


def named_attribute_elements(element: ET._Element) -> dict[str, ET._Element]:
    result: dict[str, ET._Element] = {}
    for block in direct_children(element, "attributes"):
        for attribute in direct_children(block, "attribute"):
            name = attribute.get("name", "")
            if name in result:
                fail(f"Duplicate attribute {name!r} on {local_name(element)}")
            result[name] = attribute
    return result


def ensure_attributes_block(element: ET._Element) -> ET._Element:
    blocks = direct_children(element, "attributes")
    if len(blocks) > 1:
        fail(f"Multiple attributes blocks on {local_name(element)}")
    if blocks:
        return blocks[0]
    block = ET.Element("attributes")
    element.insert(0, block)
    return block


def remove_named_attributes(element: ET._Element, names: set[str]) -> None:
    for block in direct_children(element, "attributes"):
        for attribute in list(direct_children(block, "attribute")):
            if attribute.get("name", "") in names:
                block.remove(attribute)
        if len(block) == 0:
            element.remove(block)


def set_routing_mode(leg: ET._Element, mode: str) -> None:
    attributes = named_attribute_elements(leg)
    routing = attributes.get("routingMode")
    if routing is None:
        routing = ET.SubElement(
            ensure_attributes_block(leg),
            "attribute",
            name="routingMode",
            **{"class": "java.lang.String"},
        )
    routing.set("class", "java.lang.String")
    routing.text = mode


def clear_leg_route(leg: ET._Element) -> None:
    for route in direct_children(leg, "route"):
        leg.remove(route)
    leg.attrib.pop("trav_time", None)


def largest_remainder_quotas(
    counts: pd.Series, target: int
) -> pd.Series:
    if target < 0 or target > int(counts.sum()):
        fail(f"Invalid stratified target {target} for supply {counts.sum()}")
    ideal = counts.astype(float) * target / float(counts.sum())
    quotas = np.floor(ideal).astype(int)
    remainder = target - int(quotas.sum())
    if remainder:
        order = pd.DataFrame(
            {
                "fraction": ideal - quotas,
                "label": [str(value) for value in counts.index],
            },
            index=counts.index,
        ).sort_values(["fraction", "label"], ascending=[False, True])
        for index in order.index[:remainder]:
            quotas.loc[index] += 1
    return quotas


def select_adult_car_passengers(
    adults: pd.DataFrame,
    target_persons: int = TARGET_ADULT_CAR_PASSENGER_LEGS // 2,
    seed: int = SELECTION_SEED,
) -> pd.DataFrame:
    required = {
        "person_id",
        "household_private_vehicle_count",
        "tcs_zone",
        "sex",
        "age_band_census",
    }
    missing = required - set(adults.columns)
    if missing:
        fail(f"Adult selection columns missing: {sorted(missing)}")
    eligible = adults.loc[
        adults["household_private_vehicle_count"].gt(0)
    ].copy()
    if len(eligible) < target_persons:
        fail(
            f"Only {len(eligible)} eligible adult tours for {target_persons}"
        )
    strata = ["tcs_zone", "sex", "age_band_census"]
    eligible["selection_stratum"] = eligible[strata].astype(str).agg("|".join, axis=1)
    counts = eligible.groupby("selection_stratum", sort=True).size()
    quotas = largest_remainder_quotas(counts, target_persons)
    rng = np.random.default_rng(seed)
    selected: list[pd.DataFrame] = []
    for stratum, quota in quotas.items():
        group = eligible.loc[eligible["selection_stratum"].eq(stratum)].copy()
        order = rng.permutation(len(group))
        chosen = group.iloc[order[: int(quota)]].copy()
        chosen["selection_stratum_quota"] = int(quota)
        selected.append(chosen)
    result = pd.concat(selected, ignore_index=True)
    if len(result) != target_persons or result["person_id"].duplicated().any():
        fail("Adult passenger selection did not produce unique exact target")
    return result.sort_values("person_id").reset_index(drop=True)


def pair_student_swaps(
    displaced: pd.DataFrame,
    donors: pd.DataFrame,
    seed: int = SELECTION_SEED,
) -> pd.DataFrame:
    columns = {
        "person_id",
        "student_stage",
        "tcs_zone",
        "age",
        "sex",
        "home_x",
        "home_y",
        "matsim_mode",
        "mode_detail",
        "household_private_vehicle_count",
    }
    for label, frame in (("displaced", displaced), ("donors", donors)):
        missing = columns - set(frame.columns)
        if missing:
            fail(f"{label} student columns missing: {sorted(missing)}")
    if len(displaced) != TARGET_STUDENT_SWAP_PERSONS:
        fail(
            f"Expected {TARGET_STUDENT_SWAP_PERSONS} displaced students; "
            f"found {len(displaced)}"
        )
    if not displaced["household_private_vehicle_count"].eq(0).all():
        fail("Displaced student pool contains a car-household student")
    if not donors["household_private_vehicle_count"].gt(0).all():
        fail("Student donor pool contains a no-car household")
    if not donors["matsim_mode"].isin(["pt", "walk"]).all():
        fail("Student donors must use only PT or walk")

    rng = np.random.default_rng(seed)
    unused = donors.copy().set_index("person_id", drop=False)
    pairs: list[dict[str, Any]] = []
    unmatched: list[pd.Series] = []
    group_columns = ["student_stage", "tcs_zone"]
    for group_key, need in displaced.groupby(group_columns, sort=True, dropna=False):
        stage, zone = group_key
        available = unused.loc[
            unused["student_stage"].eq(stage)
            & unused["tcs_zone"].eq(zone)
        ].copy().reset_index(drop=True)
        take = min(len(need), len(available))
        if take:
            chosen_ids = available.iloc[
                rng.permutation(len(available))[:take]
            ]["person_id"].tolist()
            need_rows = need.sort_values(["age", "sex", "person_id"])
            chosen = (
                unused.loc[chosen_ids]
                .copy()
                .reset_index(drop=True)
                .sort_values(["age", "sex", "person_id"])
            )
            for (_, displaced_row), (_, donor_row) in zip(
                need_rows.iloc[:take].iterrows(), chosen.iterrows()
            ):
                pairs.append(
                    student_pair_row(displaced_row, donor_row, "same_stage_tcs")
                )
            unused = unused.drop(index=chosen_ids)
        if take < len(need):
            unmatched.extend(
                row for _, row in need.sort_values("person_id").iloc[take:].iterrows()
            )

    for displaced_row in unmatched:
        available = unused.loc[
            unused["student_stage"].eq(displaced_row["student_stage"])
        ].copy().reset_index(drop=True)
        if available.empty:
            fail(
                "No same-stage donor for displaced student "
                f"{displaced_row['person_id']}"
            )
        dx = available["home_x"].astype(float) - float(displaced_row["home_x"])
        dy = available["home_y"].astype(float) - float(displaced_row["home_y"])
        available["distance_m"] = np.hypot(dx, dy)
        donor_row = available.sort_values(
            ["distance_m", "tcs_zone", "person_id"]
        ).iloc[0]
        pairs.append(
            student_pair_row(
                displaced_row,
                donor_row,
                "same_stage_nearest_home",
                float(donor_row["distance_m"]),
            )
        )
        unused = unused.drop(index=donor_row["person_id"])

    result = pd.DataFrame(pairs).sort_values("displaced_person_id").reset_index(drop=True)
    if len(result) != len(displaced):
        fail("Student pairing did not cover every displaced student")
    if result["displaced_person_id"].duplicated().any():
        fail("A displaced student was paired more than once")
    if result["donor_person_id"].duplicated().any():
        fail("A donor student was used more than once")
    return result


def student_pair_row(
    displaced: pd.Series,
    donor: pd.Series,
    rule: str,
    distance_m: float = 0.0,
) -> dict[str, Any]:
    return {
        "displaced_person_id": str(displaced["person_id"]),
        "donor_person_id": str(donor["person_id"]),
        "student_stage": str(displaced["student_stage"]),
        "displaced_tcs_zone": int(displaced["tcs_zone"]),
        "donor_tcs_zone": int(donor["tcs_zone"]),
        "donor_original_mode": str(donor["matsim_mode"]),
        "donor_original_mode_detail": str(donor["mode_detail"]),
        "pairing_rule": rule,
        "home_distance_m": distance_m,
    }


def matsim_paths(matsim_root: Path) -> dict[str, Path]:
    data = matsim_root / "data"
    v1 = data / "matsim_agents/hongkong/typical_weekday_5pct_v1"
    v2 = data / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
    households = data / "matsim_agents/hongkong/synthetic_households_tcs2022"
    return {
        "v1_manifest": v1 / "agent_trip_manifest.parquet",
        "residents": v1 / "sampled_resident_agents.parquet",
        "sampled_households": v1 / "sampled_households.parquet",
        "synthetic_households": households / "synthetic_households.parquet",
        "v2_facilities": v2 / "facilities_5pct_v2.xml.gz",
        "grid": data
        / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp",
        "candidate_legs": ROOT
        / "data/taxi/hongkong/processed/taxi_initial_plan_allocation_v1/taxi_candidate_leg_classification.csv",
        "fare_rules": ROOT
        / "data/taxi/hongkong/processed/taxi_fare_model_v1/taxi_fare_rules.csv",
    }


def build_target_records(
    paths: dict[str, Path]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    manifest = pd.read_parquet(paths["v1_manifest"])
    residents = pd.read_parquet(paths["residents"])
    candidates = pd.read_csv(paths["candidate_legs"], low_memory=False)

    people = residents.set_index("person_id", drop=False)
    students = residents.loc[residents["role"].eq("day_school_student")].copy()
    displaced = students.loc[
        students["mode_detail"].eq("private_vehicle")
        & students["household_private_vehicle_count"].eq(0)
    ].copy()
    donors = students.loc[
        students["household_private_vehicle_count"].gt(0)
        & students["matsim_mode"].isin(["pt", "walk"])
    ].copy()
    pairs = pair_student_swaps(displaced, donors)

    adult_people = residents.loc[
        residents["role"].eq("fixed_worker")
        & residents["mode_detail"].eq("private_car_passenger_van")
        & residents["matsim_mode"].eq("ride")
    ].copy()
    selected_adults = select_adult_car_passengers(adult_people)
    selected_adult_ids = set(selected_adults["person_id"].astype(str))

    explicit_details = {
        "taxi",
        "private_vehicle",
        "private_car_passenger_van",
        "spb",
    }
    explicit = manifest.loc[
        manifest["mode"].eq("ride")
        & manifest["mode_detail"].isin(explicit_details)
    ].copy()
    explicit = explicit.merge(
        residents[
            [
                "person_id",
                "household_private_vehicle_count",
                "age",
                "student_stage",
                "tcs_zone",
                "destination_grid_id",
            ]
        ],
        on="person_id",
        how="left",
        validate="many_to_one",
    )
    donor_mode = pairs.set_index("displaced_person_id")[
        "donor_original_mode"
    ].to_dict()
    explicit["target_mode"] = ""
    explicit["classification_source"] = ""
    taxi_mask = explicit["mode_detail"].eq("taxi")
    explicit.loc[taxi_mask, "target_mode"] = "taxi"
    explicit.loc[taxi_mask, "classification_source"] = (
        "v1_mode_detail_explicit_taxi"
    )
    school_mask = explicit["mode_detail"].eq("spb")
    explicit.loc[school_mask, "target_mode"] = "school_bus"
    explicit.loc[school_mask, "classification_source"] = (
        "v1_student_school_bus"
    )
    student_private = explicit["mode_detail"].eq("private_vehicle")
    explicit.loc[student_private, "target_mode"] = explicit.loc[
        student_private, "person_id"
    ].map(donor_mode).fillna("car_passenger")
    swapped = student_private & explicit["person_id"].isin(donor_mode)
    explicit.loc[swapped, "classification_source"] = (
        "student_swap_no_car_inherits_donor_mode"
    )
    explicit.loc[student_private & ~swapped, "classification_source"] = (
        "student_private_vehicle_car_household_retained"
    )
    adult_private = explicit["mode_detail"].eq(
        "private_car_passenger_van"
    )
    adult_selected_mask = adult_private & explicit["person_id"].isin(
        selected_adult_ids
    )
    explicit.loc[adult_selected_mask, "target_mode"] = "car_passenger"
    explicit.loc[adult_selected_mask, "classification_source"] = (
        "adult_car_household_passenger_retained"
    )
    explicit.loc[adult_private & ~adult_selected_mask, "target_mode"] = "taxi"
    explicit.loc[adult_private & ~adult_selected_mask, "classification_source"] = (
        "adult_private_passenger_reallocated_to_combined_taxi"
    )
    if explicit["target_mode"].eq("").any():
        fail("Unclassified explicit ride records remain")

    candidates = candidates.copy()
    candidates["target_mode"] = "taxi"
    candidates["classification_source"] = (
        "combined_taxi_44000_candidate_reallocation_v1"
    )
    candidates["household_private_vehicle_count"] = candidates[
        "person_id"
    ].map(people["household_private_vehicle_count"])
    candidates["age"] = candidates["person_id"].map(people["age"])
    candidates["student_stage"] = candidates["person_id"].map(
        people["student_stage"]
    )
    candidates["tcs_zone"] = candidates["person_id"].map(people["tcs_zone"])
    candidates["destination_grid_id"] = candidates["person_id"].map(
        people["destination_grid_id"]
    )

    donor_ids = set(pairs["donor_person_id"])
    donor_legs = manifest.loc[manifest["person_id"].isin(donor_ids)].copy()
    if not donor_legs.groupby("person_id").size().eq(2).all():
        fail("Student donor compulsory tours must contain exactly two legs")
    if not donor_legs["mode"].isin(["pt", "walk"]).all():
        fail("Student donor compulsory legs are not exclusively PT/walk")
    donor_legs["target_mode"] = "car_passenger"
    donor_legs["classification_source"] = (
        "student_swap_car_household_donor_to_car_passenger"
    )
    donor_legs = donor_legs.merge(
        residents[
            [
                "person_id",
                "household_private_vehicle_count",
                "age",
                "student_stage",
                "tcs_zone",
                "destination_grid_id",
            ]
        ],
        on="person_id",
        how="left",
        validate="many_to_one",
    )

    common = [
        "person_id",
        "leg_sequence",
        "population_group",
        "role",
        "origin_facility_id",
        "destination_facility_id",
        "departure_time_s",
        "target_mode",
        "classification_source",
        "household_private_vehicle_count",
        "age",
        "student_stage",
        "tcs_zone",
        "destination_grid_id",
    ]
    candidate_common = candidates.copy()
    for name in common:
        if name not in candidate_common.columns:
            candidate_common[name] = np.nan
    records = pd.concat(
        [explicit[common], candidate_common[common], donor_legs[common]],
        ignore_index=True,
    )
    records["person_id"] = records["person_id"].astype(str)
    records["leg_sequence"] = records["leg_sequence"].astype(int)
    if records.duplicated(["person_id", "leg_sequence"]).any():
        duplicate = records.loc[
            records.duplicated(["person_id", "leg_sequence"], keep=False),
            ["person_id", "leg_sequence"],
        ].head()
        fail(f"Duplicate transformation keys:\n{duplicate}")

    add_taxi_types(records, candidates, paths)
    validate_target_records(records, explicit, pairs, selected_adults)
    return records, pairs, selected_adults


def add_taxi_types(
    records: pd.DataFrame,
    candidates: pd.DataFrame,
    paths: dict[str, Path],
) -> None:
    records["taxi_type"] = ""
    candidate_taxi = candidates[
        [
            "tour_id",
            "person_id",
            "leg_sequence",
            "origin_tcs_zone",
            "destination_tcs_zone",
        ]
    ].copy()
    candidate_taxi = assign_taxi_type(candidate_taxi)
    candidate_types = candidate_taxi.set_index(
        ["person_id", "leg_sequence"]
    )["taxi_type"]
    record_index = pd.MultiIndex.from_frame(records[["person_id", "leg_sequence"]])
    records.loc[:, "taxi_type"] = candidate_types.reindex(record_index).fillna("").to_numpy()

    adult_new_taxi = records.loc[
        records["classification_source"].eq(
            "adult_private_passenger_reallocated_to_combined_taxi"
        )
    ].copy()
    if not adult_new_taxi.empty:
        adult_new_taxi = adult_new_taxi.drop(columns=["taxi_type"])
        adult_new_taxi["tour_id"] = (
            adult_new_taxi["person_id"] + "::adult_private_passenger"
        )
        adult_new_taxi = merge_facility_evidence(
            adult_new_taxi,
            paths["v1_manifest"].parent,
            paths["v2_facilities"].parent,
            paths["synthetic_households"].parent,
            paths["grid"],
        )
        adult_new_taxi = assign_taxi_type(adult_new_taxi)
        adult_types = adult_new_taxi.set_index(
            ["person_id", "leg_sequence"]
        )["taxi_type"]
        mask = records["classification_source"].eq(
            "adult_private_passenger_reallocated_to_combined_taxi"
        )
        adult_index = pd.MultiIndex.from_frame(
            records.loc[mask, ["person_id", "leg_sequence"]]
        )
        records.loc[mask, "taxi_type"] = adult_types.reindex(adult_index).to_numpy()


def validate_target_records(
    records: pd.DataFrame,
    explicit: pd.DataFrame,
    pairs: pd.DataFrame,
    selected_adults: pd.DataFrame,
) -> None:
    passenger = records.loc[
        ~records["classification_source"].eq(
            "student_swap_car_household_donor_to_car_passenger"
        )
    ]
    if len(passenger) != TARGET_PASSENGER_POOL_LEGS:
        fail(f"Passenger pool count is {len(passenger)}, not 56,360")
    counts = passenger["target_mode"].value_counts().to_dict()
    expected_pool = {
        "taxi": TARGET_TAXI_LEGS,
        "school_bus": TARGET_SCHOOL_BUS_LEGS,
        "car_passenger": 822,
        "pt": int((explicit["target_mode"] == "pt").sum()),
        "walk": int((explicit["target_mode"] == "walk").sum()),
    }
    if counts != {key: value for key, value in expected_pool.items() if value}:
        fail(f"Unexpected reallocated passenger-pool counts: {counts}")
    if len(pairs) != TARGET_STUDENT_SWAP_PERSONS:
        fail("Student swap pair count mismatch")
    if len(selected_adults) * 2 != TARGET_ADULT_CAR_PASSENGER_LEGS:
        fail("Adult car-passenger leg target mismatch")
    car_passenger = records.loc[records["target_mode"].eq("car_passenger")]
    if len(car_passenger) != TARGET_CAR_PASSENGER_LEGS:
        fail(f"Car-passenger target is {len(car_passenger)}, not 2,734")
    adult = car_passenger.loc[car_passenger["role"].eq("fixed_worker")]
    student = car_passenger.loc[
        car_passenger["role"].eq("day_school_student")
    ]
    if len(adult) != TARGET_ADULT_CAR_PASSENGER_LEGS:
        fail("Adult car-passenger count mismatch")
    if len(student) != TARGET_STUDENT_CAR_PASSENGER_LEGS:
        fail("Student car-passenger count mismatch")
    if not car_passenger["household_private_vehicle_count"].gt(0).all():
        fail("Final car-passenger target contains a no-car household")
    school = records.loc[records["target_mode"].eq("school_bus")]
    if not school["role"].eq("day_school_student").all():
        fail("School-bus target contains a non-student")
    needs_type = records["classification_source"].isin(
        [
            "combined_taxi_44000_candidate_reallocation_v1",
            "adult_private_passenger_reallocated_to_combined_taxi",
        ]
    )
    if records.loc[needs_type, "taxi_type"].eq("").any():
        fail("A newly allocated Taxi leg has no Taxi type")
    if records["target_mode"].eq("ride").any():
        fail("Target records still contain ride")


def selected_plan(person: ET._Element) -> ET._Element:
    plans = direct_children(person, "plan")
    selected = [plan for plan in plans if plan.get("selected") == "yes"]
    if len(selected) == 1:
        return selected[0]
    if len(plans) == 1:
        return plans[0]
    fail(f"Selected plan unresolved for {person.get('id', '')}")


def route_distance_m(leg: ET._Element) -> float:
    routes = direct_children(leg, "route")
    if len(routes) != 1:
        fail("New Taxi source leg must contain exactly one route")
    value = routes[0].get("distance")
    if value is None:
        fail("New Taxi source route has no distance")
    distance = float(value)
    if not math.isfinite(distance) or distance < 0:
        fail(f"Invalid Taxi route distance {distance}")
    return distance


def write_taxi_attributes(
    leg: ET._Element,
    origin: ET._Element,
    record: dict[str, Any],
    fare_rules: pd.DataFrame,
) -> None:
    taxi_type = str(record["taxi_type"])
    calculation_type = (
        taxi_type if taxi_type in fare_rules.index else "urban_taxi"
    )
    fare, _ = fare_for_distance(
        route_distance_m(leg), fare_rules.loc[calculation_type]
    )
    values = {
        "hkTaxiFareBaselineHkd": repr(float(fare)),
        "hkTaxiType": taxi_type,
        "hkTaxiFareScope": TAXI_STATIC_VALUES["hkTaxiFareScope"],
        "hkTaxiFareModelVersion": TAXI_STATIC_VALUES[
            "hkTaxiFareModelVersion"
        ],
        "hkTaxiClassificationSource": str(record["classification_source"]),
        "hkTaxiMainTripIndex": str(int(record["leg_sequence"])),
    }
    for element in (leg, origin):
        remove_named_attributes(element, set(TAXI_ATTRIBUTE_CLASSES))
        block = ensure_attributes_block(element)
        for name, class_name in TAXI_ATTRIBUTE_CLASSES.items():
            attribute = ET.SubElement(
                block, "attribute", name=name, **{"class": class_name}
            )
            attribute.text = values[name]


def source_doctype(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        prefix = handle.read(2048)
    match = re.search(r"<!DOCTYPE\s+[^>]+>", prefix)
    if not match:
        fail("Source plans DOCTYPE not found")
    return match.group(0)


def clear_top_level(element: ET._Element) -> None:
    element.clear()
    parent = element.getparent()
    if parent is not None:
        while element.getprevious() is not None:
            del parent[0]


def transform_person(
    person: ET._Element,
    records: list[dict[str, Any]],
    fare_rules: pd.DataFrame,
    counters: Counter[str],
) -> None:
    plan = selected_plan(person)
    elements = [
        element
        for element in plan
        if local_name(element) in {"activity", "leg"}
    ]
    if len(elements) % 2 != 1 or any(
        local_name(element) != ("activity" if index % 2 == 0 else "leg")
        for index, element in enumerate(elements)
    ):
        fail(f"Target plan is not strictly alternating: {person.get('id', '')}")
    legs = elements[1::2]
    activities = elements[0::2]
    for record in records:
        index = int(record["leg_sequence"])
        if index < 0 or index >= len(legs):
            fail(f"Leg index out of range: {person.get('id', '')}/{index}")
        leg = legs[index]
        origin = activities[index]
        old_mode = leg.get("mode", "")
        target_mode = str(record["target_mode"])
        if target_mode == "taxi":
            if old_mode == "ride":
                write_taxi_attributes(leg, origin, record, fare_rules)
            elif old_mode != "taxi":
                fail(
                    f"Taxi target source is {old_mode}: "
                    f"{person.get('id', '')}/{index}"
                )
            set_routing_mode(leg, "taxi")
        else:
            remove_named_attributes(leg, set(TAXI_ATTRIBUTE_CLASSES))
            remove_named_attributes(origin, set(TAXI_ATTRIBUTE_CLASSES))
            set_routing_mode(leg, target_mode)
        leg.set("mode", target_mode)
        if record["classification_source"] in {
            "student_swap_no_car_inherits_donor_mode",
            "student_swap_car_household_donor_to_car_passenger",
        }:
            clear_leg_route(leg)
            counters["student_exchange_routes_cleared"] += 1
        counters[f"transition::{old_mode}->{target_mode}"] += 1
        counters[f"target::{target_mode}"] += 1


def transform_plans(
    source: Path,
    destination: Path,
    records: pd.DataFrame,
    fare_rules: pd.DataFrame,
) -> dict[str, int]:
    by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records.to_dict("records"):
        by_person[str(record["person_id"])].append(record)
    for person_records in by_person.values():
        person_records.sort(key=lambda row: int(row["leg_sequence"]))
    counters: Counter[str] = Counter()
    seen_people: set[str] = set()
    doctype = source_doctype(source)
    with gzip.open(source, "rb") as input_handle:
        context = ET.iterparse(
            input_handle, events=("start", "end"), huge_tree=True
        )
        event, root = next(context)
        if event != "start":
            fail("Plans root start event missing")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as raw_output:
            with gzip.GzipFile(
                fileobj=raw_output,
                mode="wb",
                compresslevel=6,
                mtime=0,
            ) as gzip_output:
                with ET.xmlfile(gzip_output, encoding="utf-8") as writer:
                    writer.write_declaration()
                    writer.write_doctype(doctype)
                    with writer.element(root.tag, root.attrib):
                        for event, element in context:
                            if event != "end" or element.getparent() is not root:
                                continue
                            if local_name(element) == "person":
                                person_id = element.get("id", "")
                                person_records = by_person.get(person_id)
                                if person_records:
                                    transform_person(
                                        element,
                                        person_records,
                                        fare_rules,
                                        counters,
                                    )
                                    seen_people.add(person_id)
                            writer.write(element)
                            clear_top_level(element)
    missing = set(by_person) - seen_people
    if missing:
        fail(f"Transformation persons missing from plans: {len(missing)}")
    if counters["student_exchange_routes_cleared"] != 3_824:
        fail(
            "Expected 3,824 student exchange routes cleared; found "
            f"{counters['student_exchange_routes_cleared']}"
        )
    return dict(sorted(counters.items()))


def audit_plans(path: Path) -> dict[str, Any]:
    modes: Counter[str] = Counter()
    routing_modes: Counter[str] = Counter()
    null_routes: Counter[str] = Counter()
    taxi_leg_attributes = 0
    taxi_origin_attributes = 0
    persons = 0
    legs = 0
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), tag="person", huge_tree=True)
        for _, person in context:
            persons += 1
            plan = selected_plan(person)
            direct = [
                element
                for element in plan
                if local_name(element) in {"activity", "leg"}
            ]
            activities = direct[0::2]
            plan_legs = direct[1::2]
            for index, leg in enumerate(plan_legs):
                legs += 1
                mode = leg.get("mode", "")
                modes[mode] += 1
                attributes = named_attribute_elements(leg)
                routing = attributes.get("routingMode")
                routing_value = (routing.text or "").strip() if routing is not None else ""
                routing_modes[routing_value] += 1
                if not direct_children(leg, "route"):
                    null_routes[mode] += 1
                if mode == "taxi":
                    if set(TAXI_ATTRIBUTE_CLASSES) <= set(attributes):
                        taxi_leg_attributes += 1
                    origin_attributes = named_attribute_elements(activities[index])
                    if set(TAXI_ATTRIBUTE_CLASSES) <= set(origin_attributes):
                        taxi_origin_attributes += 1
            clear_top_level(person)
    return {
        "persons": persons,
        "legs": legs,
        "mode_counts": dict(sorted(modes.items())),
        "routing_mode_counts": dict(sorted(routing_modes.items())),
        "null_route_counts": dict(sorted(null_routes.items())),
        "taxi_leg_attribute_sets": taxi_leg_attributes,
        "taxi_origin_attribute_sets": taxi_origin_attributes,
    }


def unique_module(root: ET._Element, name: str) -> ET._Element:
    matches = root.xpath(f"./module[@name='{name}']")
    if len(matches) != 1:
        fail(f"Expected one config module {name}; found {len(matches)}")
    return matches[0]


def set_direct_param(module: ET._Element, name: str, value: str) -> None:
    matches = module.xpath(f"./param[@name='{name}']")
    if len(matches) > 1:
        fail(f"Duplicate config param {module.get('name')}.{name}")
    if matches:
        matches[0].set("value", value)
    else:
        ET.SubElement(module, "param", name=name, value=value)


def mode_params(scoring: ET._Element) -> dict[str, ET._Element]:
    result: dict[str, ET._Element] = {}
    for block in scoring.xpath("./parameterset[@type='modeParams']"):
        modes = block.xpath("./param[@name='mode']/@value")
        if len(modes) != 1 or modes[0] in result:
            fail(f"Invalid scoring modeParams mode declaration: {modes}")
        result[str(modes[0])] = block
    return result


def set_mode_scoring(
    scoring: ET._Element, mode: str, values: dict[str, str]
) -> None:
    modes = mode_params(scoring)
    block = modes.get(mode)
    if block is None:
        block = ET.SubElement(scoring, "parameterset", type="modeParams")
        ET.SubElement(block, "param", name="mode", value=mode)
    for name, value in values.items():
        set_direct_param(block, name, value)


def freeze_stage11_replanning(root: ET._Element) -> None:
    replanning = unique_module(root, "replanning")
    observed = 0
    for block in replanning.xpath("./parameterset[@type='strategysettings']"):
        names = block.xpath("./param[@name='strategyName']/@value")
        if len(names) != 1:
            fail(f"Invalid replanning strategy declaration: {names}")
        strategy = str(names[0])
        if strategy == "ChangeExpBeta":
            weight = "1"
        elif strategy in FROZEN_INNOVATION_STRATEGIES:
            weight = "0"
        else:
            fail(f"Unexpected Stage 11 replanning strategy: {strategy}")
        set_direct_param(block, "weight", weight)
        observed += 1
    if observed == 0:
        fail("No Stage 11 replanning strategies were found")


def add_teleported_mode(
    routing: ET._Element,
    mode: str,
    *,
    freespeed_factor: str | None = None,
    speed_m_s: str | None = None,
    beeline_factor: str | None = None,
) -> None:
    blocks = []
    for block in routing.xpath("./parameterset[@type='teleportedModeParameters']"):
        values = block.xpath("./param[@name='mode']/@value")
        if values == [mode]:
            blocks.append(block)
    if len(blocks) > 1:
        fail(f"Duplicate teleported routing mode {mode}")
    block = blocks[0] if blocks else ET.SubElement(
        routing, "parameterset", type="teleportedModeParameters"
    )
    set_direct_param(block, "mode", mode)
    if (freespeed_factor is None) == (speed_m_s is None):
        fail(
            f"Teleported mode {mode} requires exactly one of "
            "freespeed_factor or speed_m_s"
        )
    if freespeed_factor is not None:
        set_direct_param(
            block, "teleportedModeFreespeedFactor", freespeed_factor
        )
    if speed_m_s is not None:
        set_direct_param(block, "teleportedModeSpeed", speed_m_s)
    if beeline_factor is not None:
        set_direct_param(block, "beelineDistanceFactor", beeline_factor)


def transform_config(
    base: Path,
    destination: Path,
    plans_path: str,
    output_directory: str,
    route_only: bool,
) -> dict[str, Any]:
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(str(base), parser)
    root = tree.getroot()
    set_direct_param(unique_module(root, "plans"), "inputPlansFile", plans_path)
    controller = unique_module(root, "controller")
    set_direct_param(controller, "firstIteration", "0")
    set_direct_param(controller, "lastIteration", "0" if route_only else "10")
    set_direct_param(controller, "outputDirectory", output_directory)
    set_direct_param(controller, "overwriteFiles", "failIfDirectoryExists")
    freeze_stage11_replanning(root)
    subtour = unique_module(root, "subtourModeChoice")
    set_direct_param(subtour, "modes", "car,pt,walk")
    transit = unique_module(root, "transit")
    set_direct_param(transit, "transitModes", PHYSICAL_TRANSIT_MODES)
    routing = unique_module(root, "routing")
    set_direct_param(routing, "clearDefaultTeleportedModeParams", "true")
    add_teleported_mode(
        routing, "car_passenger", freespeed_factor="1.0"
    )
    add_teleported_mode(routing, "school_bus", freespeed_factor="1.0")
    add_teleported_mode(routing, "pt", freespeed_factor="2.0")
    add_teleported_mode(
        routing,
        "walk",
        speed_m_s="1.34",
        beeline_factor="1.3",
    )

    scoring = unique_module(root, "scoring")
    modes = mode_params(scoring)
    if "ride" in modes:
        scoring.remove(modes["ride"])
    set_mode_scoring(
        scoring,
        "car",
        {"monetaryDistanceRate": "0"},
    )
    compatibility = {
        "constant": "-1.5",
        "marginalUtilityOfTraveling_util_hr": "-6",
        "marginalUtilityOfDistance_util_m": "0",
        "monetaryDistanceRate": "-0.0015",
        "dailyMonetaryConstant": "0",
        "dailyUtilityConstant": "0",
    }
    set_mode_scoring(scoring, "car_passenger", compatibility)
    set_mode_scoring(scoring, "school_bus", compatibility)
    set_mode_scoring(
        scoring,
        "taxi",
        {
            "constant": "-9",
            "marginalUtilityOfTraveling_util_hr": "-6",
            "marginalUtilityOfDistance_util_m": "0",
            "monetaryDistanceRate": "0",
            "dailyMonetaryConstant": "0",
            "dailyUtilityConstant": "0",
        },
    )
    if root.xpath(".//param[@value='ride']"):
        fail("Generated config retains a ride-valued parameter")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        fail(f"Config output already exists: {destination}")
    tree.write(
        str(destination),
        encoding="utf-8",
        xml_declaration=True,
        doctype='<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">',
        pretty_print=True,
    )
    ET.parse(str(destination))
    return {
        "plans_path": plans_path,
        "controller_output_directory": output_directory,
        "route_only": route_only,
        "subtour_modes": "car,pt,walk",
        "physical_transit_modes": PHYSICAL_TRANSIT_MODES,
        "scoring_modes": sorted(mode_params(scoring)),
        "teleported_modes_added": [
            "car_passenger", "pt", "school_bus", "walk"
        ],
        "ride_value_occurrences": len(root.xpath(".//param[@value='ride']")),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    matsim_root = args.matsim_root.resolve()
    input_plans = args.input_plans.resolve()
    output_plans = args.output_preroute_plans.resolve()
    route_config = args.output_route_config.resolve()
    final_config = args.output_final_config.resolve()
    audit_dir = args.audit_dir.resolve()
    paths = matsim_paths(matsim_root)
    required = [input_plans, args.base_config.resolve(), *paths.values()]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        fail("Required inputs missing:\n" + "\n".join(missing))
    for output in (output_plans, route_config, final_config, audit_dir):
        if output.exists():
            fail(f"Output already exists: {output}")

    records, pairs, selected_adults = build_target_records(paths)
    fare_rules = pd.read_csv(paths["fare_rules"]).set_index("taxi_type")
    output_plans.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_plans.parent) as temp_dir:
        temporary = Path(temp_dir) / output_plans.name
        transitions = transform_plans(
            input_plans, temporary, records, fare_rules
        )
        audit = audit_plans(temporary)
        expected_null = {
            "car_passenger": 1_912,
            "pt": int(
                pairs["donor_original_mode"].eq("pt").sum() * 2
            ),
            "walk": int(
                pairs["donor_original_mode"].eq("walk").sum() * 2
            ),
        }
        expected_null = {
            key: value for key, value in expected_null.items() if value
        }
        checks = {
            "mode_counts_exact": audit["mode_counts"] == FINAL_MODE_COUNTS,
            "ride_absent": "ride" not in audit["mode_counts"],
            "taxi_attributes_complete": (
                audit["taxi_leg_attribute_sets"] == TARGET_TAXI_LEGS
                and audit["taxi_origin_attribute_sets"] == TARGET_TAXI_LEGS
            ),
            "student_exchange_null_routes_exact": (
                audit["null_route_counts"] == expected_null
            ),
            "student_pair_count_exact": len(pairs) == 956,
            "adult_tour_count_exact": len(selected_adults) == 122,
        }
        if not all(checks.values()):
            fail(f"Pre-route plans validation failed: {checks}; audit={audit}")
        temporary.replace(output_plans)

    route_config_audit = transform_config(
        args.base_config.resolve(),
        route_config,
        args.runtime_preroute_plans_path,
        args.route_output_directory,
        route_only=True,
    )
    final_config_audit = transform_config(
        args.base_config.resolve(),
        final_config,
        args.runtime_final_plans_path,
        args.route_output_directory + "_stage11",
        route_only=False,
    )
    audit_dir.mkdir(parents=True)
    pairs.to_csv(
        audit_dir / "student_mode_swap_pairs.csv", index=False, encoding="utf-8"
    )
    selected_adults.to_csv(
        audit_dir / "selected_adult_car_passenger_tours.csv",
        index=False,
        encoding="utf-8",
    )
    write_json(
        audit_dir / "no_ride_reallocation_validation.json",
        {
            "status": "validated_preroute",
            "all_checks_passed": True,
            "checks": checks,
            "policy": {
                "taxi_legs": TARGET_TAXI_LEGS,
                "student_car_passenger_legs": TARGET_STUDENT_CAR_PASSENGER_LEGS,
                "adult_car_passenger_legs": TARGET_ADULT_CAR_PASSENGER_LEGS,
                "school_bus_legs": TARGET_SCHOOL_BUS_LEGS,
                "ride_legs": 0,
                "student_swap_people_each_side": TARGET_STUDENT_SWAP_PERSONS,
            },
            "plans_audit": audit,
            "transitions": transitions,
            "student_pairing_rules": pairs["pairing_rule"].value_counts().to_dict(),
            "displaced_student_modes": pairs[
                "donor_original_mode"
            ].value_counts().to_dict(),
            "route_config": route_config_audit,
            "final_config": final_config_audit,
            "limitations": [
                "The 3,824 student exchange legs intentionally have null routes and must be passed through the route-only MATSim preparation before simulation.",
                "car_passenger and school_bus temporarily retain the historical ride scoring coefficients until separate evidence-based formulas are adopted.",
            ],
        },
    )
    print(json.dumps({"checks": checks, "plans": audit}, indent=2))


if __name__ == "__main__":
    main()
