"""Read-only validation of the canonical Hong Kong Car cost release.

The validator never rebuilds cost artifacts. It verifies the locked release
hashes, protected production inputs, canonical Parquet contents, null/zero
semantics, fixed-ownership exclusion, offline-only boundary, and Python
readability directly from an integrated checkout.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import py_compile
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml


CAR_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
CANONICAL_ROOT = CAR_ROOT / "unified_marginal_cost_interface_v1"
SCENARIOS = ("low", "base", "high")
COMPONENTS = {
    "fuel_or_electricity",
    "toll",
    "destination_parking",
}
LEGAL_ZERO_STATUSES = {
    "fuel_or_electricity": {"resolved_zero_distance_energy_zero"},
    "toll": {"confirmed_no_charge"},
    "destination_parking": {
        "resolved_home_marginal_zero_fixed_separate",
        "resolved_work_subscription_assumed_prepaid",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
        help="Integrated repository root.",
    )
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Read-only project root containing the protected MATSim inputs.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def path_is_clean(repo: Path, relative_path: Path) -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", relative_path.as_posix()],
        cwd=repo,
        check=False,
    )
    return result.returncode == 0


def finite_non_null(series: pd.Series) -> bool:
    values = series.dropna().to_numpy(dtype=float)
    return bool(np.isfinite(values).all())


def validate_scenario(
    canonical_root: Path,
    scenario: str,
) -> dict[str, Any]:
    components = pd.read_parquet(
        canonical_root / f"car_leg_marginal_cost_components_{scenario}.parquet"
    )
    summary = pd.read_parquet(
        canonical_root / f"car_leg_marginal_cost_summary_{scenario}.parquet"
    )
    component_key = ["person_id", "leg_sequence", "cost_component"]
    summary_key = ["person_id", "leg_sequence"]
    private = summary["vehicle_class"].eq("private_car")
    motorcycle = summary["vehicle_class"].eq("motorcycle")
    complete = private & summary["marginal_cost_complete"].astype(bool)
    incomplete = private & ~summary["marginal_cost_complete"].astype(bool)
    parking_unresolved = private & summary["destination_parking_hkd"].isna()
    motorcycle_components = components["vehicle_class"].eq("motorcycle")
    unresolved_or_out_of_scope = (
        components["cost_status"].astype(str).str.contains("unresolved|out_of_scope")
    )

    require(len(components) == 203154, f"{scenario}: component row count")
    require(len(summary) == 67718, f"{scenario}: summary row count")
    require(
        not components.duplicated(component_key).any(),
        f"{scenario}: duplicate component keys",
    )
    require(
        not summary.duplicated(summary_key).any(),
        f"{scenario}: duplicate summary keys",
    )
    require(
        set(components["cost_component"].unique()) == COMPONENTS,
        f"{scenario}: component registry",
    )
    require(
        components["cost_component"].value_counts().to_dict()
        == {component: 67718 for component in COMPONENTS},
        f"{scenario}: component counts",
    )
    require(int(private.sum()) == 64789, f"{scenario}: private-car count")
    require(int(motorcycle.sum()) == 2929, f"{scenario}: motorcycle count")
    require(int(complete.sum()) == 63954, f"{scenario}: complete count")
    require(int(incomplete.sum()) == 835, f"{scenario}: incomplete count")
    require(
        int(parking_unresolved.sum()) == 835,
        f"{scenario}: parking unresolved count",
    )
    require(
        summary.loc[incomplete, "behavioral_marginal_cost_hkd"].isna().all(),
        f"{scenario}: incomplete totals must be null",
    )
    require(
        summary.loc[
            motorcycle,
            [
                "fuel_or_electricity_hkd",
                "toll_hkd",
                "destination_parking_hkd",
                "behavioral_marginal_cost_hkd",
            ],
        ]
        .isna()
        .all()
        .all(),
        f"{scenario}: motorcycle costs must be null",
    )
    require(
        components.loc[motorcycle_components, "cost_hkd"].isna().all(),
        f"{scenario}: motorcycle component costs must be null",
    )
    require(
        not (
            unresolved_or_out_of_scope & components["cost_hkd"].eq(0)
        ).any(),
        f"{scenario}: unresolved/out-of-scope numeric zero",
    )
    require(
        not components["cost_component"].eq(
            "fixed_vehicle_ownership_cost"
        ).any(),
        f"{scenario}: fixed component appears in leg table",
    )
    require(
        not components["fixed_vehicle_ownership_cost_included"].astype(bool).any(),
        f"{scenario}: fixed-cost inclusion flag",
    )
    require(
        not summary["fixed_vehicle_ownership_cost_included"].astype(bool).any()
        and summary["fixed_vehicle_ownership_cost_hkd"].isna().all(),
        f"{scenario}: fixed cost appears in summary",
    )
    require(
        not summary["scoring_adoption_approved"].astype(bool).any()
        and not components["eligible_for_matsim_scoring"].astype(bool).any(),
        f"{scenario}: scoring approval flag",
    )
    formula = (
        summary.loc[complete, "fuel_or_electricity_hkd"]
        + summary.loc[complete, "toll_hkd"]
        + summary.loc[complete, "destination_parking_hkd"]
    )
    error = (
        formula - summary.loc[complete, "behavioral_marginal_cost_hkd"]
    ).abs()
    require(float(error.max()) == 0.0, f"{scenario}: formula mismatch")
    require(
        finite_non_null(components["cost_hkd"])
        and finite_non_null(summary["behavioral_marginal_cost_hkd"]),
        f"{scenario}: non-finite cost",
    )
    for component, allowed in LEGAL_ZERO_STATUSES.items():
        rows = components["cost_component"].eq(component)
        actual = set(
            components.loc[rows & components["cost_hkd"].eq(0), "cost_status"]
            .astype(str)
            .unique()
        )
        require(actual <= allowed, f"{scenario}: illegal {component} zero status")

    return {
        "component_rows": len(components),
        "summary_rows": len(summary),
        "private_car_legs": int(private.sum()),
        "motorcycle_legs": int(motorcycle.sum()),
        "complete_private_car_legs": int(complete.sum()),
        "incomplete_private_car_legs": int(incomplete.sum()),
        "parking_unresolved_private_car_legs": int(parking_unresolved.sum()),
        "formula_max_abs_error_hkd": float(error.max()),
        "unresolved_or_out_of_scope_numeric_zero_count": int(
            (
                unresolved_or_out_of_scope
                & components["cost_hkd"].eq(0)
            ).sum()
        ),
    }


def main() -> None:
    args = parse_args()
    repo = args.repository_root.resolve()
    input_root = args.input_project_root.resolve()
    car_root = repo / CAR_ROOT
    canonical_root = repo / CANONICAL_ROOT
    manifest = read_json(car_root / "canonical_car_cost_interface_manifest.json")
    release = read_json(car_root / "car_cost_release_validation.json")
    unified = read_json(canonical_root / "unified_marginal_cost_validation.json")

    require(
        manifest["canonical_interface_path"]
        == "data/transport_costs/hongkong/car_cost_v1/"
        "unified_marginal_cost_interface_v1/",
        "canonical interface path",
    )
    require(
        manifest["canonical_interface_version"]
        == "unified_marginal_cost_interface_v1",
        "canonical interface version",
    )
    require(
        manifest["canonical_interface_status"]
        == "canonical_offline_behavioral_cost_interface_candidate",
        "canonical interface status",
    )
    require(
        manifest["consumer_contract"]["canonical_components"]
        == [
            "fuel_or_electricity",
            "toll",
            "destination_parking",
        ],
        "canonical component order",
    )
    require(
        manifest["consumer_contract"]["fixed_ownership_role"]
        == "accounting_sidecar_only",
        "fixed ownership role",
    )
    require(
        not manifest["matsim_scoring_approved"]
        and not manifest["scoring_implementation_approved"]
        and not manifest["runtime_static_leg_lookup_approved"]
        and not manifest["fixed_cost_behavioral_inclusion"],
        "manifest offline-only boundary",
    )
    require(
        release["canonical_offline_interface_declared"]
        and release["release_validation_passed"]
        and not release["matsim_scoring_modified"]
        and not release["matsim_scoring_approved"]
        and not release["scoring_implementation_approved"]
        and not release["car_monetaryDistanceRate_modified"]
        and not release["marginalUtilityOfMoney_modified"]
        and not release["cost_calculation_method_modified"]
        and not release["fixed_cost_behavioral_inclusion"],
        "release offline-only boundary",
    )
    require(all(release["hard_checks"].values()), "committed release hard checks")
    require(all(unified["hard_checks"].values()), "unified hard checks")

    canonical_file_hashes = {
        path.name: sha256_file(path)
        for path in sorted(canonical_root.iterdir())
        if path.is_file()
    }
    require(
        canonical_file_hashes == manifest["canonical_interface_file_sha256"],
        "canonical file SHA256 map",
    )
    require(
        sha256_directory(canonical_root)
        == manifest["canonical_interface_bundle_sha256"],
        "canonical bundle SHA256",
    )
    candidate_fields = {
        "energy_application_v1": "energy_bundle_sha256",
        "toll_network_mapping_v1": "toll_mapping_bundle_sha256",
        "toll_rate_application_v1": "toll_rate_bundle_sha256",
        "parking_event_application_v1": "parking_bundle_sha256",
        "fixed_ownership_application_v1": "fixed_ownership_bundle_sha256",
    }
    candidate_hashes = {}
    for directory, manifest_field in candidate_fields.items():
        actual = sha256_directory(car_root / directory)
        require(actual == manifest[manifest_field], f"{directory} bundle SHA256")
        candidate_hashes[directory] = actual
    for item in manifest["superseded_path_details"]:
        path = repo / item["path"]
        require(path.is_file(), f"missing legacy path: {item['path']}")
        require(
            sha256_file(path) == item["sha256"],
            f"legacy SHA256: {item['path']}",
        )
        require(
            item["status"] == "superseded_offline_prototype"
            and item["preserved_in_place"]
            and not item["allowed_as_behavioral_scoring_input"],
            f"legacy classification: {item['path']}",
        )

    protected = release["protected_before"]["canonical_matsim_inputs"]
    protected_results = {}
    for role, record in protected.items():
        actual = sha256_file(input_root / record["path"])
        require(actual == record["sha256"], f"protected input SHA256: {role}")
        protected_results[role] = actual
    require(
        release["protected_before"]["canonical_matsim_inputs"]
        == release["protected_after"]["canonical_matsim_inputs"],
        "historical protected-input transition",
    )

    with (canonical_root / "marginal_cost_component_registry.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        registry = list(csv.DictReader(handle))
    require(len(registry) == 4, "component registry row count")
    marginal_rows = [
        row for row in registry if row["record_scope"] == "leg_marginal_cost_component"
    ]
    fixed_rows = [
        row for row in registry if row["cost_component"] == "fixed_vehicle_ownership_cost"
    ]
    require(
        {row["cost_component"] for row in marginal_rows} == COMPONENTS,
        "registry marginal components",
    )
    require(
        len(fixed_rows) == 1
        and fixed_rows[0]["behavioral_total_rule"] == "always_exclude"
        and fixed_rows[0]["behavioral_inclusion_current_model"] == "False"
        and fixed_rows[0]["eligible_for_matsim_scoring"] == "False",
        "registry fixed exclusion",
    )

    scenario_results = {
        scenario: validate_scenario(canonical_root, scenario)
        for scenario in SCENARIOS
    }
    require(
        sum(result["component_rows"] for result in scenario_results.values())
        == 609462,
        "three-scenario component row count",
    )
    base_summary = pd.read_parquet(
        canonical_root / "car_leg_marginal_cost_summary_base.parquet",
        columns=["vehicle_class", "toll_status"],
    )
    private = base_summary["vehicle_class"].eq("private_car")
    require(
        int((private & base_summary["toll_status"].eq("confirmed_charge")).sum())
        == 25858,
        "toll charged leg count",
    )
    require(
        int((private & base_summary["toll_status"].eq("confirmed_no_charge")).sum())
        == 38931,
        "toll no-charge leg count",
    )
    events_path = (
        car_root
        / "toll_rate_application_v1"
        / "car_toll_passage_events.parquet"
    )
    events_file = pq.ParquetFile(events_path)
    require(
        events_file.metadata.num_rows == 92511,
        "three-scenario toll event row count",
    )
    events = pd.read_parquet(events_path, columns=["toll_event_id", "scenario"])
    require(
        events["scenario"].value_counts().to_dict()
        == {scenario: 30837 for scenario in SCENARIOS}
        and events["toll_event_id"].nunique() == 30837,
        "physical toll passage count",
    )

    json_paths = sorted(car_root.rglob("*.json"))
    for path in json_paths:
        read_json(path)
    csv_paths = sorted(car_root.rglob("*.csv"))
    for path in csv_paths:
        pd.read_csv(path, nrows=0)
    parquet_paths = sorted(car_root.rglob("*.parquet"))
    for path in parquet_paths:
        pq.ParquetFile(path).schema_arrow

    scripts = sorted(
        (repo / "scripts/hong_kong_single_city/costs/car").glob("*.py")
    )
    compile_failures = []
    with tempfile.TemporaryDirectory(prefix="hk_car_release_pycompile_") as temp:
        for index, script in enumerate(scripts):
            try:
                py_compile.compile(
                    str(script),
                    cfile=str(Path(temp) / f"{index:02d}.pyc"),
                    doraise=True,
                )
            except py_compile.PyCompileError:
                compile_failures.append(script.name)
    require(not compile_failures, f"Car script compile failures: {compile_failures}")

    city = yaml.safe_load(
        (repo / "cities/hongkong/city.yaml").read_text(encoding="utf-8")
    )
    require(
        city["documentation"]["car_cost_model"]
        == "docs/HONG_KONG_CAR_COST_MODEL.md",
        "city documentation metadata",
    )
    require(
        city["offline_audits"]["car_cost_v1"]
        == "data/transport_costs/hongkong/car_cost_v1/"
        and city["offline_audits"]["car_cost_status"]
        == "read_only_offline_audit_not_active_matsim_scoring",
        "city offline-audit metadata",
    )
    require(
        all(
            path_is_clean(repo, path.relative_to(repo))
            for path in car_root.rglob("*")
            if path.is_file()
        ),
        "Car worktree paths differ from the merge index",
    )

    result = {
        "validation": "hong_kong_car_cost_v1_integrated_read_only_validation",
        "passed": True,
        "canonical_interface_version": manifest["canonical_interface_version"],
        "canonical_interface_status": manifest["canonical_interface_status"],
        "canonical_interface_bundle_sha256": manifest[
            "canonical_interface_bundle_sha256"
        ],
        "canonical_file_hashes_matched": len(canonical_file_hashes),
        "candidate_bundle_hashes_matched": len(candidate_hashes),
        "protected_input_hashes_matched": len(protected_results),
        "scenario_results": scenario_results,
        "three_scenario_component_rows": 609462,
        "toll_charged_legs": 25858,
        "toll_no_charge_legs": 38931,
        "physical_toll_passage_events": 30837,
        "json_files_parsed": len(json_paths),
        "csv_files_read": len(csv_paths),
        "parquet_files_readable": len(parquet_paths),
        "car_scripts_compiled": len(scripts),
        "matsim_scoring_approved": False,
        "fixed_ownership_behavioral_inclusion": False,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
