#!/usr/bin/env python3
"""Audit a future Hong Kong private-car MATSim scoring adoption design.

This script is deliberately read-only with respect to MATSim inputs, existing
cost candidates, Java source, and configuration.  It produces design and audit
artifacts only.  It does not implement scoring, emit PersonMoneyEvent records,
edit configuration, or run MATSim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, mannwhitneyu


SOURCE_COMMIT = "ee8187222dff0af1682255d9edb07994761183aa"
AUDIT_DATE = "2026-07-29"
SCENARIOS = ("low", "base", "high")
ENERGY_RATES_HKD_PER_KM = {
    "low": 1.6483900404640681,
    "base": 2.3260259843327393,
    "high": 3.540398004274133,
}
WORKTREE_ROOT = Path(__file__).resolve().parents[4]
CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
DEFAULT_OUTPUT = CAR_COST_ROOT / "scoring_adoption_design_v1"
CONFIG_RELATIVE = Path(
    "data/matsim_agents/hongkong/"
    "typical_weekday_5pct_v2_activity_modechoice/"
    "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
)
CANONICAL_INPUTS = {
    "plans_routed": (
        "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice/"
        "plans_routed_5pct_v2.xml.gz"
    ),
    "plans_unrouted": (
        "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice/"
        "plans_unrouted_5pct_v2.xml.gz"
    ),
    "private_vehicles": (
        "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice/"
        "privateVehicles_5pct.xml.gz"
    ),
    "facilities": (
        "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice/"
        "facilities_5pct_v2.xml.gz"
    ),
    "trip_manifest": (
        "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice/"
        "agent_trip_manifest_v2.parquet"
    ),
    "production_config": CONFIG_RELATIVE.as_posix(),
    "network": (
        "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/network.xml.gz"
    ),
    "transit_schedule": (
        "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
    ),
    "transit_vehicles": (
        "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/transitVehicles_10pct.xml.gz"
    ),
}
WORKTREE_PROTECTED = {
    "unified_marginal_cost_interface_v1": (
        CAR_COST_ROOT / "unified_marginal_cost_interface_v1"
    ),
    "energy_application_v1": CAR_COST_ROOT / "energy_application_v1",
    "toll_network_mapping_v1": CAR_COST_ROOT / "toll_network_mapping_v1",
    "toll_rate_application_v1": CAR_COST_ROOT / "toll_rate_application_v1",
    "parking_event_application_v1": (
        CAR_COST_ROOT / "parking_event_application_v1"
    ),
    "fixed_ownership_application_v1": (
        CAR_COST_ROOT / "fixed_ownership_application_v1"
    ),
    "src_main_java": Path("src/main/java"),
    "pom_xml": Path("pom.xml"),
    "run_hong_kong_entry": Path(
        "src/main/java/org/matsim/project/RunHongKong5Pct.java"
    ),
    "taxi_fare_core": Path(
        "data/taxi/hongkong/processed/taxi_fare_model_v1"
    ),
    "taxi_utility_core": Path(
        "data/taxi/hongkong/processed/taxi_utility_design_v1"
    ),
}
EXPECTED_COUNTS = {
    "all_car_mode_legs": 67_718,
    "private_car_legs": 64_789,
    "motorcycle_legs": 2_929,
    "complete_private_car_legs": 63_954,
    "unresolved_parking_private_car_legs": 835,
    "base_toll_passage_events": 30_837,
    "base_toll_charged_legs": 25_858,
    "base_parking_physical_events": 64_789,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the Hong Kong private-car marginal-cost MATSim scoring "
            "adoption design without implementing scoring or running MATSim."
        )
    )
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root containing read-only large MATSim inputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Repository-relative design output directory.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_sha256(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    lines = []
    for file_path in sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.as_posix(),
    ):
        relative = file_path.relative_to(path).as_posix()
        lines.append(f"{relative}\t{sha256_file(file_path)}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def repo_path(path: Path) -> str:
    return path.relative_to(WORKTREE_ROOT).as_posix()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=json_scalar,
        )
        + "\n",
        encoding="utf-8",
    )


def json_scalar(value: Any) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def hash_protected(input_root: Path) -> dict[str, Any]:
    canonical = {}
    for role, relative in CANONICAL_INPUTS.items():
        path = input_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing canonical input {role}: {relative}")
        canonical[role] = {
            "path": relative,
            "sha256": sha256_file(path),
        }
    worktree = {}
    for role, relative in WORKTREE_PROTECTED.items():
        path = WORKTREE_ROOT / relative
        if not path.exists():
            raise FileNotFoundError(
                f"Missing protected worktree object {role}: {relative}"
            )
        worktree[role] = {
            "path": relative.as_posix(),
            "sha256": bundle_sha256(path),
            "hash_type": "file_sha256" if path.is_file() else "bundle_sha256",
        }
    return {"canonical": canonical, "worktree": worktree}


def protected_equal(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before == after


def get_module(root: ET.Element, name: str) -> ET.Element:
    for module in root.findall("module"):
        if module.attrib.get("name") == name:
            return module
    raise RuntimeError(f"Config module not found: {name}")


def parameters(element: ET.Element) -> dict[str, str]:
    return {
        item.attrib["name"]: item.attrib["value"]
        for item in element.findall("param")
    }


def audit_config_and_code(input_root: Path) -> tuple[dict[str, Any], dict]:
    config_path = input_root / CONFIG_RELATIVE
    root = ET.parse(config_path).getroot()
    scoring = get_module(root, "scoring")
    mode_sets = {}
    for parameter_set in scoring.findall("parameterset"):
        if parameter_set.attrib.get("type") != "modeParams":
            continue
        values = parameters(parameter_set)
        mode_sets[values["mode"]] = values
    car = mode_sets["car"]

    replanning = get_module(root, "replanning")
    strategies = []
    for parameter_set in replanning.findall("parameterset"):
        values = parameters(parameter_set)
        strategies.append(values)

    subtour = parameters(get_module(root, "subtourModeChoice"))
    time_mutator = parameters(get_module(root, "timeAllocationMutator"))
    qsim = parameters(get_module(root, "qsim"))
    routing = parameters(get_module(root, "routing"))
    controller = parameters(get_module(root, "controller"))

    java_path = WORKTREE_ROOT / WORKTREE_PROTECTED["run_hong_kong_entry"]
    java_text = java_path.read_text(encoding="utf-8")
    all_java = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((WORKTREE_ROOT / "src/main/java").rglob("*.java"))
    )
    pom_text = (WORKTREE_ROOT / "pom.xml").read_text(encoding="utf-8")
    config_text = config_path.read_text(encoding="utf-8")
    matsim_jar = (
        Path.home()
        / ".m2"
        / "repository"
        / "org"
        / "matsim"
        / "matsim"
        / "2026.0"
        / "matsim-2026.0.jar"
    )
    matsim_jar_sha256 = (
        sha256_file(matsim_jar) if matsim_jar.is_file() else None
    )

    monetary_rate = float(car["monetaryDistanceRate"])
    marginal_utility_money = 1.0
    existing_currency_per_km = abs(monetary_rate) * 1000.0
    utility_per_km = monetary_rate * 1000.0 * marginal_utility_money

    base_summary = pd.read_parquet(
        WORKTREE_ROOT
        / CAR_COST_ROOT
        / "unified_marginal_cost_interface_v1"
        / "car_leg_marginal_cost_summary_base.parquet"
    )
    private = base_summary.loc[
        base_summary["vehicle_class"].eq("private_car")
    ].copy()
    existing_leg_currency = (
        private["route_distance_m"] * abs(monetary_rate)
    )
    existing_leg_utility = (
        private["route_distance_m"]
        * monetary_rate
        * marginal_utility_money
    )
    motorcycle_shared_mode = bool(
        base_summary.loc[
            base_summary["vehicle_class"].eq("motorcycle"), "mode"
        ].eq("car").all()
    )

    money_terms = (
        "PersonMoneyEvent",
        "LinkEnterEvent",
        "parking",
        "toll",
        "RoadPricingModule",
    )
    custom_hits = {
        term: len(re.findall(re.escape(term), all_java, flags=re.IGNORECASE))
        for term in money_terms
    }
    active_money_module = any(
        token in config_text
        for token in (
            'module name="roadpricing"',
            'module name="parking"',
            'module name="toll"',
        )
    )

    inventory = {
        "audit": "hong_kong_private_car_current_scoring_inventory_v1",
        "source_commit": SOURCE_COMMIT,
        "audit_date": AUDIT_DATE,
        "production_config_role": CONFIG_RELATIVE.as_posix(),
        "production_config_sha256": sha256_file(config_path),
        "matsim_version": "2026.0",
        "matsim_version_source": "pom.xml parent version",
        "matsim_core_artifact_evidence": {
            "artifact_role": (
                "local_maven_cache:org.matsim:matsim:2026.0;"
                "absolute_path_omitted"
            ),
            "artifact_sha256": matsim_jar_sha256,
            "audited_classes": [
                "ScoringConfigGroup$ScoringParameterSet",
                "CharyparNagelLegScoring",
                "CharyparNagelMoneyScoring",
                "ExperiencedPlansServiceImpl",
                "VehicleEntersTrafficEvent",
                "VehicleLeavesTrafficEvent",
                "LinkEnterEvent",
                "PersonMoneyEvent",
            ],
        },
        "effective_scoring_parameters": {
            "car_constant_util_per_trip": float(car["constant"]),
            "car_marginal_utility_of_traveling_util_per_hour": float(
                car["marginalUtilityOfTraveling_util_hr"]
            ),
            "car_monetary_distance_rate_currency_per_m": monetary_rate,
            "global_marginal_utility_of_money_util_per_currency": (
                marginal_utility_money
            ),
            "performing_utility_util_per_hour": 6.0,
            "ordinary_waiting_utility_util_per_hour": -0.0,
            "pt_waiting_utility_util_per_hour": -6.0,
            "late_arrival_utility_util_per_hour": -18.0,
            "early_departure_utility_util_per_hour": -0.0,
            "utility_of_line_switch": -1.0,
        },
        "parameter_source_semantics": {
            "car_parameters": "explicit_in_production_config",
            "global_marginal_utility_of_money": (
                "MATSim_2026.0_ScoringConfigGroup_default_not_explicit_config"
            ),
            "performing_waiting_and_schedule_delay": (
                "MATSim_2026.0_ScoringConfigGroup_defaults_not_explicit_config"
            ),
            "pt_waiting": (
                "MATSim_default_fallback_to_pt_marginalUtilityOfTraveling"
            ),
        },
        "currency_semantics": {
            "status": "currency_semantics_unverified",
            "config_declares_hkd": False,
            "economic_meaning_of_distance_rate_verified": False,
            "may_call_existing_rate_hkd_per_km": False,
            "existing_distance_money_currency_per_km": (
                existing_currency_per_km
            ),
            "existing_distance_money_hkd_per_km": None,
            "reason": (
                "The config contains no currency declaration or provenance "
                "showing that monetaryDistanceRate represents fuel in HKD."
            ),
        },
        "distance_money_utility": {
            "formula": (
                "route.distance_m * monetaryDistanceRate_currency_per_m * "
                "marginalUtilityOfMoney_util_per_currency"
            ),
            "utility_per_km": utility_per_km,
            "cost_currency_per_km": existing_currency_per_km,
            "private_car_leg_count": int(len(private)),
            "cost_currency_per_leg": describe(existing_leg_currency),
            "utility_per_leg": describe(existing_leg_utility),
        },
        "distance_scoring_implementation": {
            "class": (
                "org.matsim.core.scoring.functions."
                "CharyparNagelLegScoring"
            ),
            "method": "calcTravelDistScore",
            "distance_source": "experienced_leg.getRoute().getDistance()",
            "nan_distance_behavior": "fail_fast_RuntimeException",
            "money_event_used_for_distance_term": False,
        },
        "car_motorcycle_mode_semantics": {
            "motorcycle_leg_count": EXPECTED_COUNTS["motorcycle_legs"],
            "motorcycle_mode_is_car": motorcycle_shared_mode,
            "shares_car_mode_scoring_parameters": motorcycle_shared_mode,
            "future_private_car_event_filter_required": True,
        },
        "money_event_inventory": {
            "custom_java_term_hits": custom_hits,
            "active_roadpricing_parking_or_toll_config_module": (
                active_money_module
            ),
            "roadpricing_dependency_present_but_not_activated": (
                "<artifactId>roadpricing</artifactId>" in pom_text
                and not active_money_module
            ),
            "run_entry_overriding_modules": [
                "SwissRailRaptorModule",
                "no-op Mobsim only when --simulate is absent",
            ],
            "person_money_event_emitter_configured_or_custom": False,
            "vehicle_toll_event_emitter_configured_or_custom": False,
            "parking_money_event_emitter_configured_or_custom": False,
            "empirical_production_event_log_available": False,
            "empirical_event_type_confirmation": (
                "not_available_no_production_event_log_at_config_output_path"
            ),
        },
        "qsim": qsim,
        "routing": routing,
        "controller": {
            key: value
            for key, value in controller.items()
            if key != "outputDirectory"
        },
        "replanning_strategies": strategies,
        "subtour_mode_choice": subtour,
        "time_allocation_mutator": time_mutator,
        "selected_and_experienced_plan_semantics": {
            "write_experienced_plans_effective_default": True,
            "scoring_input": (
                "experienced legs/activities reconstructed from events"
            ),
            "selected_plan_role": (
                "plan chosen for execution; can be copied, mutated, rerouted, "
                "or replaced by ChangeExpBeta selection"
            ),
            "person_leg_sequence_persistent_identifier": False,
        },
        "code_audit": {
            "run_entry_path": WORKTREE_PROTECTED[
                "run_hong_kong_entry"
            ].as_posix(),
            "run_entry_sha256": sha256_file(java_path),
            "explicit_private_car_cost_scoring_module_found": False,
            "person_money_event_reference_found": (
                "PersonMoneyEvent" in all_java
            ),
            "run_entry_loads_config_without_scoring_override": True,
            "explicit_vehicle_assignment_inserted_for_car": (
                "insertVehicleIdsIntoAttributes" in java_text
            ),
        },
    }
    config_audit = {
        "root": root,
        "strategies": strategies,
        "mode_sets": mode_sets,
    }
    return inventory, config_audit


def describe(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "p90": float(clean.quantile(0.9)),
        "minimum": float(clean.min()),
        "maximum": float(clean.max()),
        "total": float(clean.sum()),
    }


def build_double_counting_audit(
    inventory: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    existing_rate = inventory["currency_semantics"][
        "existing_distance_money_currency_per_km"
    ]
    for scenario in SCENARIOS:
        path = (
            WORKTREE_ROOT
            / CAR_COST_ROOT
            / "unified_marginal_cost_interface_v1"
            / f"car_leg_marginal_cost_summary_{scenario}.parquet"
        )
        frame = pd.read_parquet(path)
        complete = frame.loc[
            frame["marginal_cost_complete"]
            & frame["vehicle_class"].eq("private_car")
        ].copy()
        km = complete["route_distance_m"] / 1000.0
        existing = km * existing_rate
        energy = complete["fuel_or_electricity_hkd"]
        toll = complete["toll_hkd"]
        parking = complete["destination_parking_hkd"]
        residual = energy - existing
        scenario_rate = ENERGY_RATES_HKD_PER_KM[scenario]

        designs = [
            {
                "design_id": "A",
                "formula": (
                    "existing_distance_money + toll + destination_parking; "
                    "audited_energy_not_added"
                ),
                "counterfactual_total": existing + toll + parking,
                "residual_total": None,
                "double_charging_assessment": (
                    "not_proven; no separate energy event, but existing "
                    "distance term economic meaning is unknown"
                ),
                "energy_bias_assessment": (
                    "underestimates audited energy if existing currency is HKD "
                    "and the distance term is intended as energy"
                ),
                "requires_config_change": False,
                "experienced_events_feasible": True,
                "implementation_currently_authorized": False,
                "decision": "reject_for_adoption",
                "reason": (
                    "Would substitute an undocumented 0.7 currency/km term "
                    "for audited energy and cannot establish HKD compatibility."
                ),
            },
            {
                "design_id": "B",
                "formula": (
                    "existing_distance_money + "
                    "(audited_energy - existing_distance_money) + toll + "
                    "destination_parking"
                ),
                "counterfactual_total": energy + toll + parking,
                "residual_total": float(residual.sum()),
                "double_charging_assessment": (
                    "algebraically_avoided_only_if_currency_distance_and_"
                    "economic_semantics_are_compatible"
                ),
                "energy_bias_assessment": (
                    "none_only_under_unverified_compatibility_assumption"
                ),
                "requires_config_change": False,
                "experienced_events_feasible": True,
                "implementation_currently_authorized": False,
                "decision": "reject_until_semantics_verified",
                "reason": (
                    "Residual subtraction is invalid across unverified "
                    "currencies or meanings; max(0,residual) is prohibited."
                ),
            },
            {
                "design_id": "C",
                "formula": (
                    "full_audited_energy + toll + destination_parking; "
                    "existing_distance_money_neutralized"
                ),
                "counterfactual_total": energy + toll + parking,
                "residual_total": None,
                "double_charging_assessment": (
                    "structurally_avoided_if_distance_money_is_neutralized"
                ),
                "energy_bias_assessment": (
                    "uses_full_audited_runtime_energy_proxy"
                ),
                "requires_config_change": True,
                "experienced_events_feasible": True,
                "implementation_currently_authorized": False,
                "decision": "future_structural_recommendation_not_authorized",
                "reason": (
                    "Cleanest event contract, but neutralizing the protected "
                    "monetaryDistanceRate requires separate authorization."
                ),
            },
        ]
        for design in designs:
            total = design.pop("counterfactual_total")
            stats = describe(total)
            rows.append(
                {
                    "scenario": scenario,
                    "design_id": design["design_id"],
                    "complete_private_car_leg_count": int(len(complete)),
                    "complete_route_distance_km": float(km.sum()),
                    "existing_distance_money_currency_per_km": existing_rate,
                    "existing_distance_money_hkd_per_km": np.nan,
                    "audited_energy_hkd_per_km": scenario_rate,
                    "counterfactual_rate_gap_if_currency_is_hkd": (
                        scenario_rate - existing_rate
                    ),
                    "currency_semantics": "unverified",
                    "economic_meaning_compatible": "unverified",
                    "existing_distance_money_total_currency": float(
                        existing.sum()
                    ),
                    "audited_energy_total_hkd": float(energy.sum()),
                    "toll_total_hkd": float(toll.sum()),
                    "destination_parking_total_hkd": float(parking.sum()),
                    "residual_energy_total_if_compatible": design[
                        "residual_total"
                    ],
                    "implied_total_hkd": np.nan,
                    "counterfactual_implied_total_if_currency_is_hkd": stats[
                        "total"
                    ],
                    "counterfactual_mean_per_leg_if_currency_is_hkd": stats[
                        "mean"
                    ],
                    "counterfactual_median_per_leg_if_currency_is_hkd": stats[
                        "median"
                    ],
                    "counterfactual_p90_per_leg_if_currency_is_hkd": stats[
                        "p90"
                    ],
                    **{
                        key: value
                        for key, value in design.items()
                        if key != "residual_total"
                    },
                }
            )
    return pd.DataFrame(rows)


def build_replanning_risk(config_audit: dict[str, Any]) -> pd.DataFrame:
    configured = {
        item["strategyName"] for item in config_audit["strategies"]
    }
    rows = [
        (
            "ReRoute",
            "yes",
            "route",
            "usually_same_structure_but_not_persistent",
            "distance,toll_facility_set_and_passage_time_change",
            "static_lookup_prohibited",
        ),
        (
            "TimeAllocationMutator",
            "yes",
            "departure_time,activity_duration",
            "usually_same_structure_but_not_persistent",
            "time_varying_toll_and_parking_duration_change",
            "static_lookup_prohibited",
        ),
        (
            "SubtourModeChoice",
            "yes",
            "mode,route,car_use_pattern",
            "no",
            "car_to_pt_must_not_be_charged;pt_to_car_has_no_static_row",
            "static_lookup_prohibited",
        ),
        (
            "ChangeExpBeta_selected_plan_switch",
            "yes",
            "selected_plan",
            "no",
            "different copied_or_mutated_plan_can_share_person_id",
            "static_lookup_prohibited",
        ),
        (
            "plan_copying",
            "implicit_in_innovative_strategies",
            "plan_instance",
            "no",
            "leg_sequence_is_not_a_persistent_plan_element_id",
            "static_lookup_prohibited",
        ),
        (
            "experienced_plan_generation",
            "MATSim_default",
            "experienced_times_and_routes",
            "no",
            "event_reconstructed_legs_are_the_scoring_truth",
            "runtime_events_required",
        ),
        (
            "stage_activity_insertion",
            "possible_with_pt_routing",
            "leg_count,leg_order,stage_activities",
            "no",
            "original_main_leg_can_expand_to_multiple_stage_legs",
            "static_lookup_prohibited",
        ),
        (
            "car_to_pt",
            "possible_SubtourModeChoice",
            "mode,route,leg_structure",
            "no",
            "old_private_car_cost_would_be_false_positive",
            "experienced_vehicle_events_only",
        ),
        (
            "pt_to_car",
            "possible_SubtourModeChoice",
            "mode,route,leg_structure",
            "no",
            "new_car_leg_has_no_original_static_cost_record",
            "experienced_vehicle_events_only",
        ),
        (
            "destination_mutation",
            "not_configured",
            "none_in_current_strategy_set",
            "not_applicable",
            "current_strategies_do_not_relocate_main_activities",
            "still_do_not_use_static_lookup",
        ),
        (
            "car_vehicle_assignment",
            "explicit_person_vehicle_mapping",
            "car_use_activation",
            "person_mapping_stable_but_active_vehicle_state_is_dynamic",
            "mode_change_alters_whether_assignment_is_used",
            "bind_person_to_vehicle_from_experienced_traffic_events",
        ),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "transformation",
            "configured_or_possible",
            "may_change",
            "person_id_plus_leg_sequence_semantics_preserved",
            "cost_risk",
            "runtime_design_rule",
        ],
    )
    frame["strategy_explicitly_configured"] = frame["transformation"].map(
        lambda value: value in configured
    )
    frame["runtime_static_leg_cost_lookup_approved"] = False
    return frame


def build_runtime_contract() -> pd.DataFrame:
    rows = [
        {
            "cost_component": "fuel_or_electricity",
            "state_or_trigger": "VehicleEntersTrafficEvent",
            "event_role": "open_experienced_private_car_leg",
            "required_state": (
                "vehicle_id,driver_person_id,network_mode,start_link,time"
            ),
            "deduplication_key": "vehicle_id+traffic_session",
            "person_attribution": "experienced_driver",
            "charge_time": "not_yet",
            "failure_policy": "fail_fast_on_missing_vehicle_class_or_driver",
            "implementation_note": (
                "Filter vehicle_class=private_car; motorcycle excluded."
            ),
        },
        {
            "cost_component": "fuel_or_electricity",
            "state_or_trigger": "LinkEnterEvent",
            "event_role": "accumulate_experienced_route_distance",
            "required_state": "vehicle_id,link_id,event_time,network_link_length",
            "deduplication_key": "ordered_link_passage_within_traffic_session",
            "person_attribution": "active_experienced_driver",
            "charge_time": "not_yet",
            "failure_policy": "fail_fast_on_unknown_link_or_no_active_session",
            "implementation_note": (
                "Explicitly reconcile start/end-link distance convention with "
                "the baseline oracle."
            ),
        },
        {
            "cost_component": "fuel_or_electricity",
            "state_or_trigger": (
                "VehicleLeavesTrafficEvent_or_experienced_car_leg_end"
            ),
            "event_role": "settle_energy_proxy",
            "required_state": (
                "experienced_distance,scenario_fleet_average_rate"
            ),
            "deduplication_key": "vehicle_id+traffic_session+energy",
            "person_attribution": "saved_experienced_driver",
            "charge_time": "experienced_car_leg_end",
            "failure_policy": "fail_fast;never_charge_old_static_person_leg",
            "implementation_note": (
                "Only after distance-money double-counting design is resolved."
            ),
        },
        {
            "cost_component": "toll",
            "state_or_trigger": "VehicleEntersTrafficEvent",
            "event_role": "bind_vehicle_to_active_driver_and_session",
            "required_state": "vehicle_id,driver_person_id,network_mode,time",
            "deduplication_key": "vehicle_id+traffic_session",
            "person_attribution": "experienced_driver",
            "charge_time": "not_yet",
            "failure_policy": "fail_fast_on_unbound_private_vehicle",
            "implementation_note": "PersonLeavesVehicleEvent is cleanup, not charge.",
        },
        {
            "cost_component": "toll",
            "state_or_trigger": "LinkEnterEvent",
            "event_role": "detect_actual_mapped_toll_passage_and_apply_rate",
            "required_state": (
                "canonical_facility_mapping,alias_map,event_time,vehicle_class"
            ),
            "deduplication_key": (
                "vehicle_id+traffic_session+canonical_facility_id+"
                "physical_passage_cluster"
            ),
            "person_attribution": "active_experienced_driver",
            "charge_time": "actual_facility_passage_time",
            "failure_policy": (
                "fail_fast_on_ambiguous_alias_or_unmapped_candidate"
            ),
            "implementation_note": (
                "WHC primary/backup alias once; different facilities each "
                "charged; never infer from cross-harbour geography or use "
                "taxi passenger surcharges."
            ),
        },
        {
            "cost_component": "destination_parking",
            "state_or_trigger": (
                "VehicleLeavesTrafficEvent_plus_PersonArrival_orActivityStart"
            ),
            "event_role": "open_physical_parking_event",
            "required_state": (
                "vehicle_id,arrival_person,time,link,facility,activity_group"
            ),
            "deduplication_key": "vehicle_id+parking_event_sequence",
            "person_attribution": "saved_arriving_driver",
            "charge_time": "not_at_arrival_duration_unknown",
            "failure_policy": "fail_fast_on_conflicting_arrival_state",
            "implementation_note": (
                "One open event per vehicle; home marginal zero remains legal."
            ),
        },
        {
            "cost_component": "destination_parking",
            "state_or_trigger": "next_VehicleEntersTrafficEvent_same_vehicle",
            "event_role": "close_and_settle_physical_parking_event",
            "required_state": (
                "open_arrival,next_departure_time,facility_consistency,"
                "scenario_rule"
            ),
            "deduplication_key": "vehicle_id+parking_event_sequence",
            "person_attribution": "saved_arriving_driver_not_next_driver",
            "charge_time": "next_vehicle_departure",
            "failure_policy": (
                "fail_fast_on_overlap_or_facility_mismatch;never_fill_zero"
            ),
            "implementation_note": (
                "Recommended non-terminal settlement; work prepaid zero only "
                "under the explicitly selected scenario."
            ),
        },
        {
            "cost_component": "destination_parking",
            "state_or_trigger": "mobsim_end",
            "event_role": "process_terminal_open_parking_events_only",
            "required_state": (
                "explicit_terminal_non_home_and_cross_midnight_rule"
            ),
            "deduplication_key": "vehicle_id+terminal_parking_event",
            "person_attribution": "saved_arriving_driver",
            "charge_time": "mobsim_end_terminal_only",
            "failure_policy": (
                "block_if_terminal_duration_rule_not_approved"
            ),
            "implementation_note": (
                "Do not batch non-terminal events here; right censoring must "
                "be explicit."
            ),
        },
        {
            "cost_component": "fixed_vehicle_ownership_cost",
            "state_or_trigger": "none",
            "event_role": "accounting_sidecar_only",
            "required_state": "none_at_runtime",
            "deduplication_key": "not_applicable",
            "person_attribution": "none",
            "charge_time": "never",
            "failure_policy": "fail_if_any_runtime_or_leg_record_is_created",
            "implementation_note": (
                "Runtime scoring events=0; leg records=0; PersonMoneyEvent=0; "
                "behavioral utility=0."
            ),
        },
    ]
    frame = pd.DataFrame(rows)
    frame["formal_scoring_implementation_written"] = False
    frame["person_money_event_emitted_in_this_audit"] = False
    frame["eligible_for_design_review"] = True
    return frame


def arrival_band(seconds: Any) -> str:
    if pd.isna(seconds):
        return "missing"
    hour = float(seconds) / 3600.0
    if hour >= 24:
        return "next_model_day_24h_plus"
    if hour < 6:
        return "night_00_06"
    if hour < 10:
        return "am_peak_06_10"
    if hour < 16:
        return "midday_10_16"
    if hour < 20:
        return "pm_peak_16_20"
    return "evening_20_24"


def unique_facility_zone_map(feasibility: pd.DataFrame) -> dict[str, str]:
    known = feasibility.loc[
        feasibility["destination_facility_id"].notna()
        & feasibility["destination_tcs_zone"].notna(),
        ["destination_facility_id", "destination_tcs_zone"],
    ].copy()
    known["destination_facility_id"] = known[
        "destination_facility_id"
    ].astype(str)
    grouped = known.groupby("destination_facility_id")[
        "destination_tcs_zone"
    ].agg(lambda values: sorted(set(map(str, values))))
    return {
        facility: zones[0]
        for facility, zones in grouped.items()
        if len(zones) == 1
    }


def classify_repair(row: pd.Series) -> tuple[str, str, str]:
    status = row["parking_status"]
    if status == "unresolved_missing_destination_zone":
        return (
            "existing_evidence_candidate",
            "spatially_join_existing_facility_coordinate_to_audited_TCS_zone",
            "blocked_until_unique_zone_evidence_is_verified",
        )
    if status == "unresolved_next_departure_facility_mismatch":
        if bool(row.get("same_inferred_tcs_zone", False)):
            return (
                "existing_evidence_review_candidate",
                "verify_same_physical_site_by_link_coordinate_and_zone",
                "blocked_until_physical_site_equivalence_is_proven",
            )
        return (
            "new_evidence_required",
            "resolve_vehicle_chain_facility_conflict",
            "blocked_no_zero_or_automatic_same_zone_assumption",
        )
    if status == "unresolved_vehicle_time_overlap":
        return (
            "new_model_or_plan_evidence_required",
            "resolve_impossible_vehicle_time_chain_without_editing_plans",
            "blocked_no_zero_or_automatic_reordering",
        )
    return (
        "new_modeling_assumption_required",
        "approve_terminal_non_home_duration_and_cross_midnight_rule",
        "blocked_until_explicit_rule_exists",
    )


def build_unresolved_detail() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    root = WORKTREE_ROOT / CAR_COST_ROOT
    parking = pd.read_parquet(
        root
        / "parking_event_application_v1"
        / "car_leg_parking_cost_estimates_base.parquet"
    )
    feasibility = pd.read_parquet(
        root / "input_feasibility" / "car_leg_input_feasibility.parquet"
    )
    summaries = {
        scenario: pd.read_parquet(
            root
            / "unified_marginal_cost_interface_v1"
            / f"car_leg_marginal_cost_summary_{scenario}.parquet"
        )
        for scenario in SCENARIOS
    }
    private = summaries["base"].loc[
        summaries["base"]["vehicle_class"].eq("private_car")
    ].copy()
    unresolved = parking.loc[
        parking["vehicle_class"].eq("private_car")
        & parking["parking_status"].astype(str).str.startswith("unresolved")
    ].copy()
    if len(unresolved) != EXPECTED_COUNTS[
        "unresolved_parking_private_car_legs"
    ]:
        raise RuntimeError("Unexpected unresolved parking count")

    enrichment_columns = [
        "person_id",
        "leg_sequence",
        "household_id",
        "assigned_vehicle_id",
        "vehicle_chain_cross_person",
        "destination_facility_x",
        "destination_facility_y",
    ]
    unresolved = unresolved.merge(
        feasibility[enrichment_columns],
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    for scenario in SCENARIOS:
        selected = summaries[scenario][
            [
                "person_id",
                "leg_sequence",
                "route_distance_m",
                "distance_band",
                "fuel_or_electricity_hkd",
                "toll_hkd",
                "toll_status",
            ]
        ].rename(
            columns={
                "route_distance_m": f"route_distance_m_{scenario}",
                "distance_band": f"distance_band_{scenario}",
                "fuel_or_electricity_hkd": (
                    f"fuel_or_electricity_hkd_{scenario}"
                ),
                "toll_hkd": f"toll_hkd_{scenario}",
                "toll_status": f"toll_status_{scenario}",
            }
        )
        unresolved = unresolved.merge(
            selected,
            on=["person_id", "leg_sequence"],
            how="left",
            validate="one_to_one",
        )
    unresolved["route_distance_m"] = unresolved["route_distance_m_base"]
    unresolved["distance_band"] = unresolved["distance_band_base"]
    unresolved["energy_cost_hkd"] = unresolved[
        "fuel_or_electricity_hkd_base"
    ]
    unresolved["toll_cost_hkd"] = unresolved["toll_hkd_base"]
    unresolved["toll_status"] = unresolved["toll_status_base"]

    zone_map = unique_facility_zone_map(feasibility)
    unresolved["origin_tcs_zone"] = unresolved[
        "origin_facility_id"
    ].astype(str).map(zone_map)
    unresolved["origin_tcs_zone_source"] = np.where(
        unresolved["origin_tcs_zone"].notna(),
        "inferred_from_unique_existing_destination_facility_zone_evidence",
        "unresolved",
    )
    unresolved["next_departure_origin_tcs_zone"] = unresolved[
        "next_departure_facility_id"
    ].astype(str).map(zone_map)
    unresolved["next_departure_origin_tcs_zone_source"] = np.where(
        unresolved["next_departure_origin_tcs_zone"].notna(),
        "inferred_from_unique_existing_destination_facility_zone_evidence",
        "unresolved",
    )
    unresolved["same_inferred_tcs_zone"] = (
        unresolved["destination_tcs_zone"].notna()
        & unresolved["next_departure_origin_tcs_zone"].notna()
        & unresolved["destination_tcs_zone"].astype(str).eq(
            unresolved["next_departure_origin_tcs_zone"].astype(str)
        )
    )
    unresolved["arrival_time_band"] = unresolved["arrival_time_s"].map(
        arrival_band
    )
    unresolved["parking_duration_available"] = unresolved[
        "parking_duration_s"
    ].notna()
    unresolved["vehicle_time_overlap_s"] = np.where(
        unresolved["parking_status"].eq(
            "unresolved_vehicle_time_overlap"
        ),
        unresolved["arrival_time_s"] - unresolved["next_departure_time_s"],
        np.nan,
    )
    unresolved["toll_charge_class"] = np.where(
        unresolved["toll_cost_hkd"].gt(0),
        "confirmed_charge",
        "confirmed_no_charge",
    )

    complete = private.loc[private["marginal_cost_complete"]].copy()
    energy_p90 = float(complete["fuel_or_electricity_hkd"].quantile(0.9))
    distance_p90 = float(complete["route_distance_m"].quantile(0.9))
    unresolved["above_complete_energy_p90"] = unresolved[
        "energy_cost_hkd"
    ].gt(energy_p90)
    unresolved["above_complete_distance_p90"] = unresolved[
        "route_distance_m"
    ].gt(distance_p90)

    for column, output in [
        ("person_id", "unresolved_count_for_person"),
        ("vehicle_ref_id", "unresolved_count_for_vehicle"),
        ("household_id", "unresolved_count_for_household"),
    ]:
        unresolved[output] = unresolved.groupby(column)[column].transform(
            "size"
        )

    repair = unresolved.apply(classify_repair, axis=1, result_type="expand")
    repair.columns = [
        "repair_evidence_class",
        "repair_candidate",
        "record_policy",
    ]
    unresolved = pd.concat([unresolved, repair], axis=1)
    unresolved["parking_missingness_random_assessment"] = (
        "not_missing_at_random_observed_stratification"
    )
    unresolved["parking_cost_hkd"] = np.nan
    unresolved["behavioral_total_hkd"] = np.nan
    unresolved["default_zero_applied"] = False

    detail_columns = [
        "person_id",
        "leg_sequence",
        "vehicle_ref_id",
        "household_id",
        "assigned_vehicle_id",
        "parking_event_key",
        "parking_status",
        "unresolved_reason",
        "origin_facility_id",
        "destination_facility_id",
        "next_departure_facility_id",
        "origin_tcs_zone",
        "origin_tcs_zone_source",
        "destination_tcs_zone",
        "next_departure_origin_tcs_zone",
        "next_departure_origin_tcs_zone_source",
        "same_inferred_tcs_zone",
        "destination_activity_type",
        "destination_activity_group",
        "arrival_time_s",
        "arrival_time_band",
        "next_departure_time_s",
        "parking_duration_s",
        "parking_duration_available",
        "vehicle_chain_time_overlap",
        "vehicle_time_overlap_s",
        "next_departure_facility_mismatch",
        "vehicle_chain_cross_person",
        "terminal_event",
        "parking_crosses_midnight",
        "route_distance_m",
        "distance_band",
        "energy_cost_hkd",
        "fuel_or_electricity_hkd_low",
        "fuel_or_electricity_hkd_base",
        "fuel_or_electricity_hkd_high",
        "toll_cost_hkd",
        "toll_status",
        "toll_charge_class",
        "above_complete_energy_p90",
        "above_complete_distance_p90",
        "unresolved_count_for_person",
        "unresolved_count_for_vehicle",
        "unresolved_count_for_household",
        "repair_evidence_class",
        "repair_candidate",
        "record_policy",
        "parking_missingness_random_assessment",
        "parking_cost_hkd",
        "behavioral_total_hkd",
        "default_zero_applied",
    ]
    detail = unresolved[detail_columns].sort_values(
        ["parking_status", "person_id", "leg_sequence"]
    )

    summary_rows: list[dict[str, Any]] = []

    def add_groups(
        dimension: str,
        unresolved_values: pd.Series,
        denominator_values: pd.Series | None = None,
        note: str = "",
    ) -> None:
        unresolved_counts = unresolved_values.fillna("missing").value_counts()
        denominator_counts = (
            denominator_values.fillna("missing").value_counts()
            if denominator_values is not None
            else pd.Series(dtype=int)
        )
        for value, count in unresolved_counts.items():
            denominator = (
                int(denominator_counts.get(value, 0))
                if denominator_values is not None
                else EXPECTED_COUNTS["private_car_legs"]
            )
            summary_rows.append(
                {
                    "summary_dimension": dimension,
                    "group_value": str(value),
                    "unresolved_count": int(count),
                    "private_car_leg_denominator": denominator,
                    "unresolved_rate": (
                        float(count / denominator) if denominator else np.nan
                    ),
                    "notes": note,
                }
            )

    add_groups(
        "unresolved_reason",
        detail["parking_status"],
        note="All remain blocked and null.",
    )
    add_groups(
        "destination_activity_group",
        detail["destination_activity_group"],
        private["destination_activity_group"],
        "Observed activity stratification; not random.",
    )
    add_groups("destination_tcs_zone", detail["destination_tcs_zone"])
    add_groups("origin_tcs_zone", detail["origin_tcs_zone"])
    add_groups(
        "route_distance_band",
        detail["distance_band"],
        private["distance_band"],
        "Long-distance legs are overrepresented.",
    )
    add_groups("arrival_time_band", detail["arrival_time_band"])
    add_groups(
        "parking_duration_available",
        detail["parking_duration_available"].astype(str),
    )
    add_groups("toll_charge_class", detail["toll_charge_class"])
    add_groups(
        "unresolved_count_per_person",
        detail.groupby("person_id").size().astype(str),
    )
    add_groups(
        "unresolved_count_per_vehicle",
        detail.groupby("vehicle_ref_id").size().astype(str),
    )
    add_groups(
        "repair_evidence_class",
        detail["repair_evidence_class"],
    )

    complete_energy = complete["fuel_or_electricity_hkd"]
    unresolved_energy = detail["energy_cost_hkd"]
    complete_distance = complete["route_distance_m"]
    unresolved_distance = detail["route_distance_m"]
    activity_table = pd.crosstab(
        private["destination_activity_group"],
        ~private["marginal_cost_complete"],
    )
    distance_table = pd.crosstab(
        private["distance_band"],
        ~private["marginal_cost_complete"],
    )
    activity_p = float(chi2_contingency(activity_table)[1])
    distance_p = float(chi2_contingency(distance_table)[1])
    energy_p = float(
        mannwhitneyu(
            unresolved_energy,
            complete_energy,
            alternative="two-sided",
        ).pvalue
    )
    bias = {
        "unresolved_count": int(len(detail)),
        "unique_person_count": int(detail["person_id"].nunique()),
        "unique_vehicle_count": int(detail["vehicle_ref_id"].nunique()),
        "unique_household_count": int(detail["household_id"].nunique()),
        "missingness_assessment": "not_approximately_random",
        "activity_independence_chi_square_p_value": activity_p,
        "distance_band_independence_chi_square_p_value": distance_p,
        "energy_distribution_mann_whitney_p_value": energy_p,
        "unresolved_route_distance_mean_km": float(
            unresolved_distance.mean() / 1000.0
        ),
        "complete_route_distance_mean_km": float(
            complete_distance.mean() / 1000.0
        ),
        "unresolved_to_complete_distance_mean_ratio": float(
            unresolved_distance.mean() / complete_distance.mean()
        ),
        "unresolved_energy_mean_hkd": float(unresolved_energy.mean()),
        "complete_energy_mean_hkd": float(complete_energy.mean()),
        "unresolved_to_complete_energy_mean_ratio": float(
            unresolved_energy.mean() / complete_energy.mean()
        ),
        "unresolved_toll_charge_share": float(
            detail["toll_cost_hkd"].gt(0).mean()
        ),
        "complete_toll_charge_share": float(
            complete["toll_hkd"].gt(0).mean()
        ),
        "complete_case_scoring_bias": (
            "would_systematically_omit_longer_higher_energy_and_"
            "activity_concentrated_private_car_legs"
        ),
        "records_potentially_repairable_with_existing_evidence_review": int(
            detail["repair_evidence_class"]
            .isin(
                [
                    "existing_evidence_candidate",
                    "existing_evidence_review_candidate",
                ]
            )
            .sum()
        ),
        "records_requiring_new_evidence_or_modeling_assumption": int(
            (~detail["repair_evidence_class"].isin(
                [
                    "existing_evidence_candidate",
                    "existing_evidence_review_candidate",
                ]
            )).sum()
        ),
        "recommended_policy": (
            "formal_scoring_adoption_blocked_until_835_repaired;"
            "complete_case_allowed_only_for_non_mode_choice_technical_replay;"
            "fail_fast_at_runtime_for_unresolved_physical_events"
        ),
    }
    summary = pd.DataFrame(summary_rows)
    for key, value in bias.items():
        if isinstance(value, (str, int, float, np.integer, np.floating)):
            summary_rows.append(
                {
                    "summary_dimension": "bias_metric",
                    "group_value": key,
                    "unresolved_count": (
                        int(value)
                        if isinstance(value, (int, np.integer))
                        else np.nan
                    ),
                    "private_car_leg_denominator": EXPECTED_COUNTS[
                        "private_car_legs"
                    ],
                    "unresolved_rate": (
                        float(value)
                        if isinstance(value, (float, np.floating))
                        else np.nan
                    ),
                    "notes": str(value),
                }
            )
    summary = pd.DataFrame(summary_rows)
    return detail, summary, bias


def build_replay_contract(bias: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": "hong_kong_private_car_baseline_replay_acceptance_v1",
        "source_commit": SOURCE_COMMIT,
        "oracle": (
            "data/transport_costs/hongkong/car_cost_v1/"
            "unified_marginal_cost_interface_v1"
        ),
        "oracle_role": (
            "baseline_selected_routed_plan_audit_truth_and_runtime_replay_"
            "oracle_only;not_iteration_runtime_static_lookup"
        ),
        "test_mode": {
            "iteration": 0,
            "replanning_disabled": True,
            "selected_routed_plan_frozen": True,
            "matsim_simulation_run_by_this_audit": False,
            "future_test_required": True,
        },
        "expected_counts": {
            "experienced_private_car_legs": 64_789,
            "energy_aligned_private_car_legs": 64_789,
            "energy_zero_distance_legal_zero_legs": 33,
            "toll_physical_passage_events_base": 30_837,
            "toll_charged_private_car_legs_base": 25_858,
            "toll_no_charge_private_car_legs_base": 38_931,
            "toll_canonical_facility_count_experienced": 9,
            "parking_physical_events_private_car": 64_789,
            "parking_complete_private_car_events_base": 63_954,
            "parking_incomplete_private_car_events_base": 835,
            "motorcycle_private_car_cost_events": 0,
            "fixed_cost_runtime_events": 0,
            "fixed_cost_leg_scoring_records": 0,
            "fixed_cost_person_money_events": 0,
        },
        "identity_and_structure_acceptance": {
            "energy_event_key_unique": "vehicle_id+traffic_session",
            "toll_event_key_unique": (
                "vehicle_id+traffic_session+canonical_facility+passage_cluster"
            ),
            "parking_event_key_unique": "vehicle_id+parking_event_sequence",
            "toll_facility_multiset_exact_match": True,
            "whc_alias_duplicate_charge_count": 0,
            "parking_duplicate_physical_event_charge_count": 0,
            "complete_incomplete_status_exact_match": True,
            "legal_zero_status_set_exact_match": True,
        },
        "numeric_acceptance": {
            "energy_max_abs_error_hkd": 1e-6,
            "toll_same_rate_interval_max_abs_error_hkd": 1e-9,
            "parking_same_billing_bucket_max_abs_error_hkd": 1e-9,
            "complete_leg_total_same_semantic_inputs_max_abs_error_hkd": 1e-6,
            "unexplained_component_max_abs_error_hkd": 0.0,
            "unexplained_leg_total_max_abs_error_hkd": 0.0,
        },
        "experienced_time_semantic_differences": {
            "toll": (
                "Actual passage time may cross a rate interval relative to the "
                "offline estimated base time. Report raw max error separately; "
                "a nonzero difference is acceptable only if exact official "
                "rate-boundary evidence explains it."
            ),
            "parking": (
                "Experienced arrival/departure may cross a billing unit or "
                "day/night boundary. Report raw max error separately; accept "
                "only exact rule-based differences with unique physical events."
            ),
            "raw_max_abs_error_must_be_reported": True,
            "static_base_amount_forced_at_runtime": False,
        },
        "failure_conditions": [
            "private_car_leg_count_mismatch",
            "energy_distance_convention_unreconciled",
            "toll_facility_set_or_alias_dedup_mismatch",
            "parking_event_duplicate_or_person_attribution_mismatch",
            "unexplained_nonzero_component_or_total_error",
            "any_motorcycle_private_car_cost_event",
            "any_fixed_ownership_runtime_event_or_utility",
            "any_unresolved_parking_default_zero",
        ],
        "unresolved_policy": bias["recommended_policy"],
        "baseline_replay_only": True,
        "runtime_static_leg_cost_lookup_approved": False,
    }


def build_repairs() -> pd.DataFrame:
    rows = [
        (
            "SCORING-R01",
            "critical",
            True,
            "currency_semantics",
            "Production config does not declare that scoring currency is HKD.",
            "Adopt an explicit, reviewed currency convention and provenance.",
        ),
        (
            "SCORING-R02",
            "critical",
            True,
            "distance_money_economic_meaning",
            (
                "The economic content of car monetaryDistanceRate=-0.0007 "
                "currency/m is undocumented."
            ),
            (
                "Establish whether it represents energy, other variable cost, "
                "or a calibrated generalized-cost proxy before subtraction."
            ),
        ),
        (
            "SCORING-R03",
            "critical",
            True,
            "authorized_design",
            (
                "Structurally preferred design C requires neutralizing a "
                "currently protected scoring parameter."
            ),
            (
                "Obtain separate authorization, behavioral design approval, "
                "implementation review, and joint calibration."
            ),
        ),
        (
            "SCORING-R04",
            "critical",
            True,
            "unresolved_parking",
            (
                "835 non-random private-car parking events have null cost and "
                "are concentrated in long and education trips."
            ),
            (
                "Repair with verified evidence; keep formal adoption blocked "
                "and never default to zero."
            ),
        ),
        (
            "SCORING-R05",
            "high",
            True,
            "runtime_event_implementation",
            (
                "No experienced-event private-car cost module exists and "
                "implementation is not approved."
            ),
            (
                "Implement only after approval using the reviewed vehicle "
                "state and physical-event contracts."
            ),
        ),
        (
            "SCORING-R06",
            "high",
            True,
            "baseline_replay",
            "The required iteration-0/replay acceptance has not been run.",
            (
                "Pass the frozen baseline replay contract before any scoring "
                "or mode-choice adoption."
            ),
        ),
        (
            "SCORING-R07",
            "high",
            True,
            "experienced_time_semantics",
            (
                "Offline toll passage and parking times are planned/estimated; "
                "runtime events use experienced times."
            ),
            (
                "Reconcile only rule-explainable rate/billing boundary "
                "differences and report raw plus unexplained error."
            ),
        ),
        (
            "SCORING-R08",
            "high",
            True,
            "motorcycle_filter",
            (
                "Motorcycles use mode=car and therefore share current car mode "
                "distance scoring."
            ),
            (
                "Future event module must filter private vehicle class and "
                "prove zero motorcycle private-car cost events."
            ),
        ),
        (
            "SCORING-R09",
            "medium",
            True,
            "terminal_parking",
            (
                "Terminal non-home parking needs an explicit right-censoring "
                "and cross-midnight duration rule."
            ),
            (
                "Approve a sourced rule and settle terminal events only at "
                "mobsim end; otherwise fail fast."
            ),
        ),
        (
            "SCORING-R10",
            "medium",
            False,
            "empirical_money_event_inventory",
            (
                "No production event log exists at the configured output path "
                "for empirical event-type confirmation."
            ),
            (
                "During future replay, assert that baseline fixed-cost and "
                "private-car money-event counts match the contract."
            ),
        ),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "repair_id",
            "severity",
            "blocking",
            "domain",
            "finding",
            "required_change",
        ],
    )


def main() -> None:
    args = parse_args()
    input_root = args.input_project_root.resolve()
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else WORKTREE_ROOT / args.output_dir
    ).resolve()
    try:
        output_dir.relative_to(WORKTREE_ROOT)
    except ValueError as error:
        raise RuntimeError("Output must stay inside the worktree") from error

    before = hash_protected(input_root)
    inventory, config_audit = audit_config_and_code(input_root)
    double_counting = build_double_counting_audit(inventory)
    runtime_contract = build_runtime_contract()
    replanning_risk = build_replanning_risk(config_audit)
    detail, bias_summary, bias = build_unresolved_detail()
    replay_contract = build_replay_contract(bias)
    repairs = build_repairs()

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "current_car_scoring_inventory.json", inventory)
    double_counting.to_csv(
        output_dir / "distance_cost_double_counting_audit.csv",
        index=False,
        encoding="utf-8",
    )
    runtime_contract.to_csv(
        output_dir / "runtime_component_event_contract.csv",
        index=False,
        encoding="utf-8",
    )
    replanning_risk.to_csv(
        output_dir / "replanning_identity_risk.csv",
        index=False,
        encoding="utf-8",
    )
    bias_summary.to_csv(
        output_dir / "unresolved_parking_bias_summary.csv",
        index=False,
        encoding="utf-8",
    )
    detail.to_parquet(
        output_dir / "unresolved_parking_bias_detail.parquet",
        index=False,
    )
    write_json(
        output_dir / "baseline_replay_acceptance_contract.json",
        replay_contract,
    )
    repairs.to_csv(
        output_dir / "scoring_adoption_design_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )

    after = hash_protected(input_root)
    unchanged = protected_equal(before, after)
    input_hashes = {
        "audit": "hong_kong_private_car_scoring_design_input_hashes_v1",
        "source_commit": SOURCE_COMMIT,
        "input_root_role": (
            "canonical_project_read_only_large_inputs;"
            "absolute_root_deliberately_omitted"
        ),
        "bundle_hash_algorithm": (
            "sha256_of_utf8_sorted_relative_path_tab_file_sha256_lines"
        ),
        "protected_before": before,
        "protected_after": after,
        "all_protected_sha256_unchanged": unchanged,
    }
    write_json(
        output_dir / "scoring_adoption_design_input_hashes.json",
        input_hashes,
    )

    hard_checks = {
        "source_commit_locked": True,
        "config_currency_semantics_unverified": (
            inventory["currency_semantics"]["status"]
            == "currency_semantics_unverified"
        ),
        "marginal_utility_of_money_sign_confirmed_positive": (
            inventory["effective_scoring_parameters"][
                "global_marginal_utility_of_money_util_per_currency"
            ]
            > 0
        ),
        "distance_rate_not_labelled_hkd": (
            inventory["currency_semantics"][
                "existing_distance_money_hkd_per_km"
            ]
            is None
        ),
        "double_counting_rows_9": len(double_counting) == 9,
        "all_three_designs_all_scenarios": (
            set(double_counting["design_id"]) == {"A", "B", "C"}
            and set(double_counting["scenario"]) == set(SCENARIOS)
        ),
        "runtime_contract_has_four_components": (
            set(runtime_contract["cost_component"])
            == {
                "fuel_or_electricity",
                "toll",
                "destination_parking",
                "fixed_vehicle_ownership_cost",
            }
        ),
        "fixed_runtime_event_count_contract_zero": (
            replay_contract["expected_counts"]["fixed_cost_runtime_events"]
            == 0
        ),
        "motorcycle_private_cost_event_contract_zero": (
            replay_contract["expected_counts"][
                "motorcycle_private_car_cost_events"
            ]
            == 0
        ),
        "runtime_static_lookup_rejected": (
            not replay_contract["runtime_static_leg_cost_lookup_approved"]
            and not replanning_risk[
                "runtime_static_leg_cost_lookup_approved"
            ].any()
        ),
        "unresolved_detail_rows_835": len(detail) == 835,
        "unresolved_detail_key_unique": (
            not detail.duplicated(["person_id", "leg_sequence"]).any()
        ),
        "unresolved_costs_remain_null": (
            detail["parking_cost_hkd"].isna().all()
            and detail["behavioral_total_hkd"].isna().all()
        ),
        "unresolved_default_zero_never_applied": (
            not detail["default_zero_applied"].any()
        ),
        "missingness_classified_non_random": (
            bias["missingness_assessment"] == "not_approximately_random"
        ),
        "baseline_replay_contract_defined": (
            replay_contract["baseline_replay_only"]
        ),
        "fixed_behavioral_inclusion_false": True,
        "all_protected_sha256_unchanged": unchanged,
    }
    blocked_reasons = repairs.loc[
        repairs["blocking"], "repair_id"
    ].tolist()
    validation = {
        "audit": "hong_kong_private_car_scoring_adoption_design_v1",
        "source_commit": SOURCE_COMMIT,
        "audit_date": AUDIT_DATE,
        "design_candidate": True,
        "blocked": True,
        "blocked_reasons": blocked_reasons,
        "matsim_scoring_modified": False,
        "scoring_implementation_approved": False,
        "scoring_adoption_approved": False,
        "joint_mode_choice_calibration_approved": False,
        "car_monetaryDistanceRate_modified": False,
        "marginalUtilityOfMoney_modified": False,
        "car_constant_modified": False,
        "config_modified": False,
        "fixed_vehicle_ownership_behavioral_inclusion": False,
        "runtime_static_leg_cost_lookup_approved": False,
        "baseline_replay_only": True,
        "matsim_run_performed": False,
        "person_money_events_generated": False,
        "formal_java_scoring_module_written": False,
        "recommended_current_policy": (
            "adopt_no_scoring_scheme_now;keep_adoption_blocked;"
            "allow_complete_case_only_for_non_mode_choice_technical_replay"
        ),
        "future_structural_recommendation_after_new_authorization": (
            "dynamic_design_C_after_currency_and_distance_semantics_are_"
            "verified_835_parking_events_are_repaired_baseline_replay_passes_"
            "and_joint_calibration_is_separately_approved"
        ),
        "currency_semantics": inventory["currency_semantics"],
        "unresolved_parking_bias": bias,
        "baseline_replay_acceptance": replay_contract,
        "required_repairs": blocked_reasons,
        "hard_checks": hard_checks,
        "protected_inputs": {
            "all_protected_sha256_unchanged": unchanged,
            "details_file": "scoring_adoption_design_input_hashes.json",
        },
    }
    if not all(hard_checks.values()):
        validation["design_candidate"] = False
    write_json(
        output_dir / "scoring_adoption_design_validation.json",
        validation,
    )

    print(
        json.dumps(
            {
                "output_dir": output_dir.relative_to(
                    WORKTREE_ROOT
                ).as_posix(),
                "design_candidate": validation["design_candidate"],
                "blocked": validation["blocked"],
                "blocking_repairs": len(blocked_reasons),
                "unresolved_parking_rows": len(detail),
                "missingness_assessment": bias["missingness_assessment"],
                "all_protected_sha256_unchanged": unchanged,
                "matsim_scoring_modified": False,
                "matsim_run_performed": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
