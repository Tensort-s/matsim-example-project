#!/usr/bin/env python3
"""Finalize the canonical Hong Kong private-car offline cost interface v1.

The script does not recalculate costs. It preserves the initial top-level
prototype in place, records its exact hashes, declares the already-built
unified marginal-cost interface canonical, and validates version consistency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


WORKTREE_ROOT = Path(__file__).resolve().parents[4]
CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
CANONICAL_INTERFACE = (
    CAR_COST_ROOT / "unified_marginal_cost_interface_v1"
)
CANONICAL_INTERFACE_VERSION = "unified_marginal_cost_interface_v1"
CANONICAL_SOURCE_COMMIT = (
    "ee8187222dff0af1682255d9edb07994761183aa"
)
CANONICAL_BUILD_INPUT_COMMIT = (
    "f3fa7b6ad510929d087da29df32d5f2be375e5eb"
)
INITIAL_PROTOTYPE_COMMIT = (
    "797f103e4cb12fbcc83a8cf9669bdbb1feb13b48"
)
MANIFEST_GENERATION_PARENT_COMMIT = (
    "663c19f45cefa344c615804c35c4efc14167e256"
)
RELEASE_DATE = "2026-07-29"
SCENARIOS = ("low", "base", "high")

LEGACY_RESULT_PATHS = [
    CAR_COST_ROOT / "car_leg_cost_estimates_low.parquet",
    CAR_COST_ROOT / "car_leg_cost_estimates_base.parquet",
    CAR_COST_ROOT / "car_leg_cost_estimates_high.parquet",
    CAR_COST_ROOT / "car_cost_model_validation.json",
    CAR_COST_ROOT / "car_cost_summary_by_component.csv",
    CAR_COST_ROOT / "car_cost_summary_by_distance.csv",
    CAR_COST_ROOT / "car_cost_summary_by_destination.csv",
    CAR_COST_ROOT / "car_cost_summary_by_activity.csv",
]
HISTORICAL_SUPPORT_PATHS = [
    CAR_COST_ROOT / "car_cost_source_manifest.json",
    CAR_COST_ROOT / "car_energy_cost_parameters.csv",
    CAR_COST_ROOT / "car_toll_rules.csv",
    CAR_COST_ROOT / "car_parking_cost_rules.csv",
]
CANDIDATE_BUNDLES = {
    "energy_application_v1": CAR_COST_ROOT / "energy_application_v1",
    "toll_network_mapping_v1": (
        CAR_COST_ROOT / "toll_network_mapping_v1"
    ),
    "toll_rate_application_v1": CAR_COST_ROOT / "toll_rate_application_v1",
    "parking_event_application_v1": (
        CAR_COST_ROOT / "parking_event_application_v1"
    ),
    "fixed_ownership_application_v1": (
        CAR_COST_ROOT / "fixed_ownership_application_v1"
    ),
}
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
    "config": (
        "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice/"
        "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
    ),
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
    "src_main_java": Path("src/main/java"),
    "pom_xml": Path("pom.xml"),
    "run_hong_kong_entry": Path(
        "src/main/java/org/matsim/project/RunHongKong5Pct.java"
    ),
}
OUTPUT_PATHS = {
    "manifest": CAR_COST_ROOT / "canonical_car_cost_interface_manifest.json",
    "transition": CAR_COST_ROOT / "car_cost_version_transition_audit.csv",
    "validation": CAR_COST_ROOT / "car_cost_release_validation.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Read-only canonical project root containing large MATSim inputs.",
    )
    return parser.parse_args()


def absolute_worktree(path: Path) -> Path:
    return path if path.is_absolute() else WORKTREE_ROOT / path


def repo_path(path: Path) -> str:
    return absolute_worktree(path).relative_to(WORKTREE_ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: Path) -> str:
    """Match the bundle digest used by the unified interface builder."""
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


def hash_path(path: Path) -> str:
    return sha256_file(path) if path.is_file() else sha256_directory(path)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            default=json_scalar,
        )
        + "\n",
        encoding="utf-8",
    )


def json_scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def require_paths(input_root: Path) -> None:
    required = [
        *LEGACY_RESULT_PATHS,
        *HISTORICAL_SUPPORT_PATHS,
        CANONICAL_INTERFACE,
        *CANDIDATE_BUNDLES.values(),
        *WORKTREE_PROTECTED.values(),
    ]
    missing = [
        repo_path(path)
        for path in required
        if not absolute_worktree(path).exists()
    ]
    for relative in CANONICAL_INPUTS.values():
        if not (input_root / relative).is_file():
            missing.append(relative)
    if missing:
        raise FileNotFoundError(f"Missing release inputs: {missing}")


def protected_hashes(input_root: Path) -> dict[str, Any]:
    return {
        "canonical_matsim_inputs": {
            role: {
                "path": relative,
                "sha256": sha256_file(input_root / relative),
            }
            for role, relative in sorted(CANONICAL_INPUTS.items())
        },
        "legacy_top_level_results": {
            repo_path(path): sha256_file(absolute_worktree(path))
            for path in LEGACY_RESULT_PATHS
        },
        "historical_supporting_assets": {
            repo_path(path): sha256_file(absolute_worktree(path))
            for path in HISTORICAL_SUPPORT_PATHS
        },
        "canonical_interface": {
            "path": repo_path(CANONICAL_INTERFACE),
            "bundle_sha256": sha256_directory(
                absolute_worktree(CANONICAL_INTERFACE)
            ),
            "file_sha256": {
                candidate.relative_to(
                    absolute_worktree(CANONICAL_INTERFACE)
                ).as_posix(): sha256_file(candidate)
                for candidate in sorted(
                    absolute_worktree(CANONICAL_INTERFACE).iterdir()
                )
                if candidate.is_file()
            },
        },
        "component_candidates": {
            role: {
                "path": repo_path(path),
                "bundle_sha256": sha256_directory(absolute_worktree(path)),
            }
            for role, path in CANDIDATE_BUNDLES.items()
        },
        "code_and_build": {
            role: {
                "path": repo_path(path),
                "sha256": hash_path(absolute_worktree(path)),
                "hash_type": (
                    "file_sha256"
                    if absolute_worktree(path).is_file()
                    else "directory_bundle_sha256"
                ),
            }
            for role, path in WORKTREE_PROTECTED.items()
        },
    }


def canonical_counts() -> dict[str, Any]:
    interface = absolute_worktree(CANONICAL_INTERFACE)
    summaries = {
        scenario: pd.read_parquet(
            interface / f"car_leg_marginal_cost_summary_{scenario}.parquet"
        )
        for scenario in SCENARIOS
    }
    components = {
        scenario: pd.read_parquet(
            interface
            / f"car_leg_marginal_cost_components_{scenario}.parquet"
        )
        for scenario in SCENARIOS
    }
    base = summaries["base"]
    toll = pd.read_parquet(
        absolute_worktree(
            CAR_COST_ROOT
            / "toll_rate_application_v1"
            / "car_leg_toll_cost_estimates_base.parquet"
        )
    )
    toll_events = pd.read_parquet(
        absolute_worktree(
            CAR_COST_ROOT
            / "toll_rate_application_v1"
            / "car_toll_passage_events.parquet"
        )
    )
    private = base["vehicle_class"].eq("private_car")
    motorcycle = base["vehicle_class"].eq("motorcycle")
    complete = base["marginal_cost_complete"] & private
    incomplete = ~base["marginal_cost_complete"] & private
    base_components = components["base"]
    unresolved_component = base_components["cost_status"].astype(str).str.startswith(
        ("unresolved", "out_of_scope")
    )
    return {
        "canonical_car_leg_count": int(len(base)),
        "canonical_private_car_leg_count": int(private.sum()),
        "canonical_motorcycle_leg_count": int(motorcycle.sum()),
        "canonical_complete_leg_count": int(complete.sum()),
        "canonical_incomplete_leg_count": int(incomplete.sum()),
        "canonical_parking_incomplete_leg_count": int(
            (
                private
                & base["destination_parking_status"]
                .astype(str)
                .str.startswith("unresolved")
            ).sum()
        ),
        "canonical_toll_charged_leg_count": int(
            toll["toll_status"].eq("confirmed_charge").sum()
        ),
        "canonical_toll_no_charge_leg_count": int(
            toll["toll_status"].eq("confirmed_no_charge").sum()
        ),
        "canonical_toll_physical_passage_event_count": int(
            (
                toll_events["scenario"].eq("base")
                & toll_events["vehicle_class"].eq("private_car")
                & toll_events["toll_status"].eq("confirmed_charge")
            ).sum()
        ),
        "scenario_summary_row_counts": {
            scenario: int(len(frame))
            for scenario, frame in summaries.items()
        },
        "scenario_component_row_counts": {
            scenario: int(len(frame))
            for scenario, frame in components.items()
        },
        "unresolved_or_out_of_scope_component_count_base": int(
            unresolved_component.sum()
        ),
        "unresolved_or_out_of_scope_numeric_zero_count_base": int(
            (
                unresolved_component
                & base_components["cost_hkd"].eq(0)
            ).sum()
        ),
        "incomplete_behavioral_total_null": bool(
            base.loc[
                incomplete, "behavioral_marginal_cost_hkd"
            ].isna().all()
        ),
        "fixed_component_leg_row_count": int(
            base_components["cost_component"]
            .eq("fixed_vehicle_ownership_cost")
            .sum()
        ),
        "fixed_cost_included_true_count": int(
            base["fixed_vehicle_ownership_cost_included"].sum()
        ),
        "fixed_cost_leg_value_non_null_count": int(
            base["fixed_vehicle_ownership_cost_hkd"].notna().sum()
        ),
        "scoring_adoption_approved_true_count": int(
            base["scoring_adoption_approved"].sum()
        ),
    }


def legacy_counts() -> dict[str, Any]:
    validation = json.loads(
        absolute_worktree(
            CAR_COST_ROOT / "car_cost_model_validation.json"
        ).read_text(encoding="utf-8")
    )
    component = pd.read_csv(
        absolute_worktree(
            CAR_COST_ROOT / "car_cost_summary_by_component.csv"
        )
    )
    base_toll = component.loc[
        component["scenario"].eq("base")
        & component["cost_component"].eq("toll")
    ].iloc[0]
    return {
        "legacy_confirmed_charged_private_car_legs": int(
            validation["toll_status_counts_private_car_standardized"][
                "confirmed_charge"
            ]
        ),
        "legacy_confirmed_no_charge_private_car_legs": int(
            validation["toll_status_counts_private_car_standardized"][
                "confirmed_no_charge"
            ]
        ),
        "legacy_base_toll_total_hkd": float(
            base_toll["total_cost_hkd"]
        ),
        "legacy_status": "superseded_offline_prototype",
    }


def build_manifest(
    hashes: dict[str, Any],
    counts: dict[str, Any],
    legacy: dict[str, Any],
) -> dict[str, Any]:
    candidate = hashes["component_candidates"]
    canonical_files = hashes["canonical_interface"]["file_sha256"]
    superseded_details = [
        {
            "path": repo_path(path),
            "sha256": hashes["legacy_top_level_results"][
                repo_path(path)
            ],
            "status": "superseded_offline_prototype",
            "preserved_in_place": True,
            "allowed_as_behavioral_scoring_input": False,
            "replacement": repo_path(CANONICAL_INTERFACE),
        }
        for path in LEGACY_RESULT_PATHS
    ]
    return {
        "manifest": "hong_kong_private_car_cost_canonical_interface_v1",
        "release_date": RELEASE_DATE,
        "canonical_interface_path": (
            repo_path(CANONICAL_INTERFACE) + "/"
        ),
        "canonical_interface_version": CANONICAL_INTERFACE_VERSION,
        "canonical_interface_status": (
            "canonical_offline_behavioral_cost_interface_candidate"
        ),
        "source_commit": CANONICAL_SOURCE_COMMIT,
        "canonical_build_input_commit": CANONICAL_BUILD_INPUT_COMMIT,
        "manifest_generation_parent_commit": (
            MANIFEST_GENERATION_PARENT_COMMIT
        ),
        "canonical_interface_bundle_sha256": hashes[
            "canonical_interface"
        ]["bundle_sha256"],
        "canonical_interface_file_sha256": canonical_files,
        "bundle_sha256_algorithm": (
            "SHA256 over sorted relative paths encoded as "
            "8-byte-big-endian-length+UTF8-path followed by file bytes"
        ),
        "energy_bundle_sha256": candidate["energy_application_v1"][
            "bundle_sha256"
        ],
        "toll_mapping_bundle_sha256": candidate[
            "toll_network_mapping_v1"
        ]["bundle_sha256"],
        "toll_rate_bundle_sha256": candidate["toll_rate_application_v1"][
            "bundle_sha256"
        ],
        "parking_bundle_sha256": candidate[
            "parking_event_application_v1"
        ]["bundle_sha256"],
        "fixed_ownership_bundle_sha256": candidate[
            "fixed_ownership_application_v1"
        ]["bundle_sha256"],
        "canonical_car_leg_count": counts["canonical_car_leg_count"],
        "canonical_private_car_leg_count": counts[
            "canonical_private_car_leg_count"
        ],
        "canonical_motorcycle_leg_count": counts[
            "canonical_motorcycle_leg_count"
        ],
        "canonical_complete_leg_count": counts[
            "canonical_complete_leg_count"
        ],
        "canonical_incomplete_leg_count": counts[
            "canonical_incomplete_leg_count"
        ],
        "canonical_toll_charged_leg_count": counts[
            "canonical_toll_charged_leg_count"
        ],
        "canonical_toll_no_charge_leg_count": counts[
            "canonical_toll_no_charge_leg_count"
        ],
        "canonical_toll_physical_passage_event_count": counts[
            "canonical_toll_physical_passage_event_count"
        ],
        "fixed_cost_behavioral_inclusion": False,
        "matsim_scoring_approved": False,
        "scoring_implementation_approved": False,
        "runtime_static_leg_lookup_approved": False,
        "legacy_initial_model": {
            "source_commit": INITIAL_PROTOTYPE_COMMIT,
            **legacy,
        },
        "superseded_paths": [
            item["path"] for item in superseded_details
        ],
        "superseded_path_details": superseded_details,
        "supersession_reason": (
            "The initial top-level prototype matched only direct numeric "
            "toll-feature IDs and reported 1,008 charged legs. Later official "
            "facility-to-network topology mapping, alias resolution, ordered "
            "physical passage-event reconstruction, and time-dependent rate "
            "application produce 25,858 charged legs, 38,931 confirmed "
            "no-charge legs, and 30,837 physical passage events. The unified "
            "interface also preserves 835 parking-incomplete legs as null."
        ),
        "consumer_contract": {
            "future_offline_behavioral_integration_must_read": (
                repo_path(CANONICAL_INTERFACE) + "/"
            ),
            "legacy_top_level_leg_totals_must_not_be_read": True,
            "legacy_files_preserved_for_provenance": True,
            "canonical_components": [
                "fuel_or_electricity",
                "toll",
                "destination_parking",
            ],
            "fixed_ownership_role": "accounting_sidecar_only",
        },
    }


def build_transition_audit(
    hashes: dict[str, Any],
    counts: dict[str, Any],
    legacy: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in LEGACY_RESULT_PATHS:
        relative = repo_path(path)
        rows.append(
            {
                "artifact_path": relative,
                "artifact_role": "initial_top_level_result",
                "version_status": "superseded_offline_prototype",
                "hash_type": "file_sha256",
                "sha256": hashes["legacy_top_level_results"][relative],
                "source_commit": INITIAL_PROTOTYPE_COMMIT,
                "preserved_in_place": True,
                "canonical_offline_integration_source": False,
                "allowed_as_current_matsim_scoring_input": False,
                "replacement_path": repo_path(CANONICAL_INTERFACE) + "/",
                "legacy_confirmed_charged_private_car_legs": legacy[
                    "legacy_confirmed_charged_private_car_legs"
                ],
                "canonical_confirmed_charged_private_car_legs": counts[
                    "canonical_toll_charged_leg_count"
                ],
                "transition_reason": (
                    "superseded_by_topology_mapped_physical_passage_event_"
                    "toll_and_unified_null_preserving_interface"
                ),
            }
        )
    for path in HISTORICAL_SUPPORT_PATHS:
        relative = repo_path(path)
        rows.append(
            {
                "artifact_path": relative,
                "artifact_role": "initial_prototype_supporting_asset",
                "version_status": (
                    "historical_provenance_not_canonical_behavior_interface"
                ),
                "hash_type": "file_sha256",
                "sha256": hashes["historical_supporting_assets"][relative],
                "source_commit": INITIAL_PROTOTYPE_COMMIT,
                "preserved_in_place": True,
                "canonical_offline_integration_source": False,
                "allowed_as_current_matsim_scoring_input": False,
                "replacement_path": repo_path(CANONICAL_INTERFACE) + "/",
                "legacy_confirmed_charged_private_car_legs": legacy[
                    "legacy_confirmed_charged_private_car_legs"
                ],
                "canonical_confirmed_charged_private_car_legs": counts[
                    "canonical_toll_charged_leg_count"
                ],
                "transition_reason": (
                    "retained_as_initial_model_provenance_only"
                ),
            }
        )
    rows.append(
        {
            "artifact_path": repo_path(CANONICAL_INTERFACE) + "/",
            "artifact_role": "canonical_offline_behavioral_cost_interface",
            "version_status": (
                "canonical_offline_behavioral_cost_interface_candidate"
            ),
            "hash_type": "directory_bundle_sha256",
            "sha256": hashes["canonical_interface"]["bundle_sha256"],
            "source_commit": CANONICAL_SOURCE_COMMIT,
            "preserved_in_place": True,
            "canonical_offline_integration_source": True,
            "allowed_as_current_matsim_scoring_input": False,
            "replacement_path": "",
            "legacy_confirmed_charged_private_car_legs": legacy[
                "legacy_confirmed_charged_private_car_legs"
            ],
            "canonical_confirmed_charged_private_car_legs": counts[
                "canonical_toll_charged_leg_count"
            ],
            "transition_reason": (
                "current_authoritative_offline_interface;"
                "MATSim_scoring_still_not_approved"
            ),
        }
    )
    for role, details in hashes["component_candidates"].items():
        rows.append(
            {
                "artifact_path": details["path"] + "/",
                "artifact_role": f"canonical_source_dependency:{role}",
                "version_status": "audited_canonical_dependency",
                "hash_type": "directory_bundle_sha256",
                "sha256": details["bundle_sha256"],
                "source_commit": CANONICAL_BUILD_INPUT_COMMIT,
                "preserved_in_place": True,
                "canonical_offline_integration_source": False,
                "allowed_as_current_matsim_scoring_input": False,
                "replacement_path": repo_path(CANONICAL_INTERFACE) + "/",
                "legacy_confirmed_charged_private_car_legs": legacy[
                    "legacy_confirmed_charged_private_car_legs"
                ],
                "canonical_confirmed_charged_private_car_legs": counts[
                    "canonical_toll_charged_leg_count"
                ],
                "transition_reason": (
                    "read_only_dependency_of_unified_canonical_interface"
                ),
            }
        )
    return pd.DataFrame(rows)


def verify_manifest_hashes(manifest: dict[str, Any]) -> dict[str, bool]:
    candidate = {
        "energy_bundle_sha256": "energy_application_v1",
        "toll_mapping_bundle_sha256": "toll_network_mapping_v1",
        "toll_rate_bundle_sha256": "toll_rate_application_v1",
        "parking_bundle_sha256": "parking_event_application_v1",
        "fixed_ownership_bundle_sha256": "fixed_ownership_application_v1",
    }
    checks = {
        "canonical_interface_bundle_sha256_matches": (
            manifest["canonical_interface_bundle_sha256"]
            == sha256_directory(absolute_worktree(CANONICAL_INTERFACE))
        )
    }
    interface = absolute_worktree(CANONICAL_INTERFACE)
    checks["canonical_interface_file_sha256_all_match"] = all(
        (interface / relative).is_file()
        and sha256_file(interface / relative) == expected
        for relative, expected in manifest[
            "canonical_interface_file_sha256"
        ].items()
    )
    for field, role in candidate.items():
        checks[f"{field}_matches"] = (
            manifest[field]
            == sha256_directory(absolute_worktree(CANDIDATE_BUNDLES[role]))
        )
    checks["superseded_file_sha256_all_match"] = all(
        sha256_file(absolute_worktree(Path(item["path"])))
        == item["sha256"]
        for item in manifest["superseded_path_details"]
    )
    return checks


def main() -> None:
    args = parse_args()
    input_root = args.input_project_root.resolve()
    require_paths(input_root)

    protected_before = protected_hashes(input_root)
    counts = canonical_counts()
    legacy = legacy_counts()
    manifest = build_manifest(protected_before, counts, legacy)
    transition = build_transition_audit(
        protected_before,
        counts,
        legacy,
    )

    manifest_path = absolute_worktree(OUTPUT_PATHS["manifest"])
    transition_path = absolute_worktree(OUTPUT_PATHS["transition"])
    validation_path = absolute_worktree(OUTPUT_PATHS["validation"])
    write_json(manifest_path, manifest)
    transition.to_csv(transition_path, index=False, encoding="utf-8")

    manifest_hash_checks = verify_manifest_hashes(manifest)
    protected_after = protected_hashes(input_root)
    expected = {
        "canonical_car_leg_count": 67_718,
        "canonical_private_car_leg_count": 64_789,
        "canonical_motorcycle_leg_count": 2_929,
        "canonical_complete_leg_count": 63_954,
        "canonical_incomplete_leg_count": 835,
        "canonical_parking_incomplete_leg_count": 835,
        "canonical_toll_charged_leg_count": 25_858,
        "canonical_toll_no_charge_leg_count": 38_931,
        "canonical_toll_physical_passage_event_count": 30_837,
    }
    hard_checks = {
        f"{key}_matches_expected": counts[key] == value
        for key, value in expected.items()
    }
    hard_checks.update(manifest_hash_checks)
    hard_checks.update(
        {
            "legacy_prototype_charged_leg_count_1008": (
                legacy["legacy_confirmed_charged_private_car_legs"]
                == 1_008
            ),
            "legacy_files_preserved_in_place": all(
                absolute_worktree(path).is_file()
                for path in LEGACY_RESULT_PATHS
            ),
            "all_legacy_paths_marked_superseded": (
                len(manifest["superseded_paths"])
                == len(LEGACY_RESULT_PATHS)
                and transition.loc[
                    transition["artifact_role"].eq(
                        "initial_top_level_result"
                    ),
                    "version_status",
                ].eq("superseded_offline_prototype").all()
            ),
            "canonical_interface_is_only_offline_integration_source": (
                transition.loc[
                    transition["canonical_offline_integration_source"]
                ].shape[0]
                == 1
                and transition.loc[
                    transition["canonical_offline_integration_source"],
                    "artifact_path",
                ].iloc[0]
                == repo_path(CANONICAL_INTERFACE) + "/"
            ),
            "no_current_matsim_scoring_input_approved": (
                not transition[
                    "allowed_as_current_matsim_scoring_input"
                ].any()
            ),
            "unresolved_count_nonzero": (
                counts["canonical_incomplete_leg_count"] > 0
            ),
            "unresolved_or_out_of_scope_never_numeric_zero": (
                counts[
                    "unresolved_or_out_of_scope_numeric_zero_count_base"
                ]
                == 0
            ),
            "incomplete_behavioral_total_null": counts[
                "incomplete_behavioral_total_null"
            ],
            "fixed_ownership_not_in_leg_components": (
                counts["fixed_component_leg_row_count"] == 0
            ),
            "fixed_ownership_not_in_leg_totals": (
                counts["fixed_cost_included_true_count"] == 0
                and counts["fixed_cost_leg_value_non_null_count"] == 0
            ),
            "matsim_scoring_not_approved": (
                not manifest["matsim_scoring_approved"]
                and counts["scoring_adoption_approved_true_count"] == 0
            ),
            "all_protected_inputs_unchanged": (
                protected_before == protected_after
            ),
            "transition_audit_row_count_18": len(transition) == 18,
        }
    )
    validation = {
        "validation": "hong_kong_car_cost_v1_canonical_release_validation",
        "release_date": RELEASE_DATE,
        "manifest_path": repo_path(OUTPUT_PATHS["manifest"]),
        "manifest_sha256": sha256_file(manifest_path),
        "transition_audit_path": repo_path(OUTPUT_PATHS["transition"]),
        "transition_audit_sha256": sha256_file(transition_path),
        "canonical_interface_path": (
            repo_path(CANONICAL_INTERFACE) + "/"
        ),
        "canonical_interface_version": CANONICAL_INTERFACE_VERSION,
        "canonical_offline_interface_declared": True,
        "release_validation_passed": all(hard_checks.values()),
        "blocked": False,
        "blocked_semantics": (
            "False means canonical offline version transition is valid; "
            "it does not approve MATSim scoring."
        ),
        "matsim_scoring_modified": False,
        "matsim_scoring_approved": False,
        "matsim_scoring_blocked": True,
        "scoring_implementation_approved": False,
        "car_monetaryDistanceRate_modified": False,
        "marginalUtilityOfMoney_modified": False,
        "cost_calculation_method_modified": False,
        "energy_parameters_modified": False,
        "toll_parameters_modified": False,
        "parking_parameters_modified": False,
        "fixed_cost_behavioral_inclusion": False,
        "legacy_results_overwritten": False,
        "legacy_results_moved": False,
        "legacy_status": "superseded_offline_prototype",
        "counts": counts,
        "legacy_counts": legacy,
        "manifest_sha256_checks": manifest_hash_checks,
        "hard_checks": hard_checks,
        "protected_before": protected_before,
        "protected_after": protected_after,
        "all_protected_inputs_unchanged": (
            protected_before == protected_after
        ),
    }
    if not validation["release_validation_passed"]:
        validation["blocked"] = True
    write_json(validation_path, validation)

    print(
        json.dumps(
            {
                "canonical_interface_path": (
                    repo_path(CANONICAL_INTERFACE) + "/"
                ),
                "legacy_status": "superseded_offline_prototype",
                "release_validation_passed": validation[
                    "release_validation_passed"
                ],
                "legacy_toll_charged_legs": legacy[
                    "legacy_confirmed_charged_private_car_legs"
                ],
                "canonical_toll_charged_legs": counts[
                    "canonical_toll_charged_leg_count"
                ],
                "canonical_toll_physical_events": counts[
                    "canonical_toll_physical_passage_event_count"
                ],
                "canonical_complete_private_car_legs": counts[
                    "canonical_complete_leg_count"
                ],
                "canonical_incomplete_private_car_legs": counts[
                    "canonical_incomplete_leg_count"
                ],
                "all_protected_inputs_unchanged": validation[
                    "all_protected_inputs_unchanged"
                ],
                "matsim_scoring_approved": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
