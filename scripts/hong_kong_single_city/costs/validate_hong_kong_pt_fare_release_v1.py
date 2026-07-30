"""Validate the canonical offline Hong Kong PT fare release.

This validator is intentionally read-only.  Registered SHA256 values are
checked against Git's canonical index bytes so that Windows CRLF checkout
conversion cannot create a false release failure.  A registered worktree path
must still be clean relative to the index, so real content changes do fail.
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

import pandas as pd


RELEASE_ROOT = Path("data/transport_costs/hongkong/pt_fare_v1")
WITHDRAWN_OUTPUTS = (
    "official_fare_distance_curve.csv",
    "pt_passenger_trip_fare_estimates.parquet",
    "pt_passenger_trip_fare_estimates_sample.csv",
    "pt_trip_fare_validation.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validation of the canonical offline Hong Kong PT fare "
            "release, registry, protected inputs, and 20-check release record."
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root. Defaults to the root containing this script.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    return result.stdout


def index_sha256(repo: Path, relative_path: str) -> str:
    data = git(repo, "show", f":{relative_path}", binary=True)
    assert isinstance(data, bytes)
    return hashlib.sha256(data).hexdigest()


def path_is_clean(repo: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", relative_path],
        cwd=repo,
        check=False,
    )
    return result.returncode == 0


def bool_value(value: object) -> bool:
    return str(value).strip().lower() == "true"


def main() -> None:
    args = parse_args()
    repo = args.repository_root.resolve()
    release_root = repo / RELEASE_ROOT
    manifest = read_json(release_root / "canonical_pt_fare_interface_manifest.json")
    committed_release = read_json(release_root / "pt_fare_release_validation.json")

    inventory = pd.read_csv(release_root / "transit_schedule_inventory.csv")
    mode_counts = inventory["transport_mode"].value_counts().to_dict()
    mtr = pd.read_parquet(
        release_root / "mtr_station_od_v1/mtr_station_od_fare_rules.parquet"
    )
    light_rail = pd.read_parquet(
        release_root
        / "light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet"
    )
    gmb = pd.read_parquet(release_root / "gmb_fare_v1/gmb_fare_rules.parquet")
    ferry = pd.read_parquet(
        release_root / "ferry_fare_v1/ferry_fare_rules.parquet"
    )
    bus_core = pd.read_parquet(
        release_root / "bus_fare_v1/bus_fare_rules.parquet"
    )
    bus_simulation = pd.read_parquet(
        release_root
        / "bus_fare_simulation_v1/bus_simulation_fare_rules.parquet"
    )
    production_pt = pd.read_parquet(
        release_root / "pt_passenger_trip_fare_audit.parquet"
    )

    with (release_root / "pt_fare_layer_registry.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        registry = list(csv.DictReader(handle))

    registered_hash_results: list[dict[str, object]] = []
    for row in registry:
        for relative_path, expected_sha256 in json.loads(row["SHA256"]).items():
            actual_sha256 = index_sha256(repo, relative_path)
            clean = path_is_clean(repo, relative_path)
            registered_hash_results.append(
                {
                    "transport_mode": row["transport_mode"],
                    "path": relative_path,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                    "matched": actual_sha256 == expected_sha256,
                    "worktree_clean_against_index": clean,
                }
            )

    protected = pd.read_csv(release_root / "protected_input_hash_comparison.csv")
    scripts = sorted(
        (repo / "scripts/hong_kong_single_city/costs/pt").glob("*.py")
    )
    compile_failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hk_pt_release_pycompile_") as temp_dir:
        for index, script in enumerate(scripts):
            try:
                py_compile.compile(
                    str(script),
                    cfile=str(Path(temp_dir) / f"{index:02d}.pyc"),
                    doraise=True,
                )
            except py_compile.PyCompileError:
                compile_failures.append(script.name)

    diff_check = subprocess.run(
        ["git", "diff", "--check"], cwd=repo, check=False
    ).returncode == 0
    cached_diff_check = subprocess.run(
        ["git", "diff", "--cached", "--check"], cwd=repo, check=False
    ).returncode == 0

    mtr_domestic_available = int(
        (
            (mtr["fare_network_scope"] == "domestic_mtr_station_od")
            & (mtr["record_status"] == "available")
        ).sum()
    )
    light_rail_available = int((light_rail["record_status"] == "available").sum())
    bus_quality = {
        str(key): int(value)
        for key, value in bus_simulation["cost_quality"].value_counts().items()
    }
    production_costs_null = bool(production_pt["cost_hkd"].isna().all())
    production_unresolved = int(production_pt["cost_hkd"].isna().sum())

    transfer_unmodelled = (
        manifest["transfer_concession_status"] == "unmodelled_for_all_modes"
        and all("not_modelled" in row["transfer_concession_status"] for row in registry)
    )
    protected_unchanged = (
        len(protected) == 8
        and protected["unchanged"].map(bool_value).all()
        and (protected["sha256_before"] == protected["sha256_after"]).all()
    )
    withdrawn_present = [
        name for name in WITHDRAWN_OUTPUTS if (release_root / name).exists()
    ]
    registry_modes = {row["transport_mode"] for row in registry}
    registry_hashes_match = (
        len(registry) == 5
        and registry_modes == {"mtr", "light_rail", "gmb", "ferry", "bus"}
        and len(registered_hash_results) == 16
        and all(
            bool(item["matched"]) and bool(item["worktree_clean_against_index"])
            for item in registered_hash_results
        )
    )
    no_global_adult_octopus = (
        not manifest["top_level_catalog_status"]["global_adult_octopus_semantics"]
        and {row["passenger_type_semantics"] for row in registry}
        != {"adult_only"}
        and {row["payment_medium_semantics"] for row in registry}
        != {"Octopus_only"}
    )

    checks = [
        ("01_schedule_routes_equal_3613", len(inventory) == 3613),
        ("02_bus_routes_equal_2363", int(mode_counts.get("bus", 0)) == 2363),
        ("03_gmb_routes_equal_1161", int(mode_counts.get("gmb", 0)) == 1161),
        ("04_train_routes_equal_30", int(mode_counts.get("train", 0)) == 30),
        (
            "05_light_rail_routes_equal_20",
            int(mode_counts.get("light_rail", 0)) == 20,
        ),
        ("06_ferry_routes_equal_39", int(mode_counts.get("ferry", 0)) == 39),
        ("07_mtr_domestic_available_OD_equal_9216", mtr_domestic_available == 9216),
        (
            "08_light_rail_available_OD_equal_4624",
            light_rail_available == 4624,
        ),
        ("09_gmb_required_forward_pairs_equal_97521", len(gmb) == 97521),
        ("10_ferry_required_forward_pairs_equal_60", len(ferry) == 60),
        ("11_bus_core_active_rules_equal_754133", len(bus_core) == 754133),
        (
            "12_bus_simulation_rules_equal_771666",
            len(bus_simulation) == 771666,
        ),
        (
            "13_production_PT_total_priced_unresolved_equal_557104_0_557104",
            len(production_pt) == 557104
            and production_costs_null
            and production_unresolved == 557104,
        ),
        ("14_transfer_concessions_remain_unmodelled", transfer_unmodelled),
        ("15_eight_protected_MATSim_inputs_unchanged", protected_unchanged),
        ("16_withdrawn_distance_median_outputs_absent", not withdrawn_present),
        ("17_all_registry_SHA256_values_match", registry_hashes_match),
        ("18_global_adult_octopus_semantic_removed", no_global_adult_octopus),
        (
            "19_all_23_PT_fare_Python_scripts_compile",
            len(scripts) == 23 and not compile_failures,
        ),
        ("20_git_diff_check_passes", diff_check and cached_diff_check),
    ]
    check_records = [
        {"name": name, "passed": bool(passed)} for name, passed in checks
    ]
    committed_checks = {
        item["name"]: item["passed"] for item in committed_release["checks"]
    }
    committed_record_matches = (
        committed_release["status"] == "passed"
        and len(committed_checks) == 20
        and all(committed_checks.get(name) is True for name, _ in checks)
    )
    all_passed = bool(
        all(bool(passed) for _, passed in checks) and committed_record_matches
    )

    result = {
        "schema_version": "hong_kong_pt_fare_release_runtime_validation_v1",
        "status": "passed" if all_passed else "failed",
        "release_status": manifest["release_status"],
        "checks": check_records,
        "committed_20_check_record_matches": committed_record_matches,
        "registry_validation": {
            "registry_row_count": len(registry),
            "path_hash_check_count": len(registered_hash_results),
            "all_matched": registry_hashes_match,
            "path_hash_results": registered_hash_results,
        },
        "independent_counts": {
            "schedule_routes": len(inventory),
            "routes_by_mode": {key: int(value) for key, value in mode_counts.items()},
            "mtr_domestic_available_OD": mtr_domestic_available,
            "light_rail_available_OD": light_rail_available,
            "gmb_required_forward_pairs": len(gmb),
            "ferry_required_forward_pairs": len(ferry),
            "bus_core_active_rules": len(bus_core),
            "bus_simulation_rules": len(bus_simulation),
            "bus_simulation_quality_counts": bus_quality,
            "production_pt_leg_count": len(production_pt),
            "priced_production_pt_leg_count": int(production_pt["cost_hkd"].notna().sum()),
            "unresolved_production_pt_leg_count": production_unresolved,
        },
        "protected_input_validation": {
            "files_checked": len(protected),
            "all_unchanged": bool(protected_unchanged),
        },
        "withdrawn_outputs_present": withdrawn_present,
        "code_validation": {
            "python_script_count": len(scripts),
            "compile_failures": compile_failures,
            "git_diff_check_passed": diff_check,
            "git_cached_diff_check_passed": cached_diff_check,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if not all_passed:
        failed = [name for name, passed in checks if not passed]
        raise SystemExit(f"Release validation failed: {failed}")


if __name__ == "__main__":
    main()
