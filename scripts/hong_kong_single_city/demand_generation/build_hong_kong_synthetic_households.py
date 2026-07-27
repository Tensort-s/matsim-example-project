#!/usr/bin/env python3
"""Build Hong Kong synthetic households, members, vehicles, and drivers."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"

SIZE_COLUMNS = ("dhz_1", "dhz_2", "dhz_3", "dhz_4", "dhz_5", "dhz_6")
INCOME_COLUMNS = ("dhi_1", "dhi_2", "dhi_3", "dhi_4", "dhi_5", "dhi_6", "dhi_7")
HOUSING_COLUMNS = ("dh_pub", "dh_s", "dh_pri", "dh_non", "dh_tem")
AGE_COLUMNS = ("age_1", "age_2", "age_3", "age_4", "age_5")

INCOME_LABELS = {
    1: "less_than_6000",
    2: "6000_9999",
    3: "10000_19999",
    4: "20000_29999",
    5: "30000_39999",
    6: "40000_59999",
    7: "60000_plus",
}
HOUSING_LABELS = {
    1: "public_rental",
    2: "subsidised_home_ownership",
    3: "private_permanent",
    4: "non_domestic",
    5: "temporary",
}
TCS_HOUSING_RATES = {
    1: 0.055,
    2: 0.121,
    3: 0.251,
    4: 0.172,
    5: 0.172,
}
TCS_SIZE_RATES = {1: 0.070, 2: 0.139, 3: 0.182, 4: 0.250, 5: 0.347}
TCS_INCOME_RATES = {1: 0.037, 2: 0.059, 3: 0.106, 4: 0.170, 5: 0.381}
OVERALL_PV_RATE = 0.172


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--seed", type=int, default=202202)
    parser.add_argument("--sample-rate", type=float, default=1.0)
    parser.add_argument("--effect-shrinkage", type=float, default=0.5)
    return parser.parse_args()


def input_paths(data_root: Path) -> dict[str, Path]:
    census = data_root / "boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP"
    school = data_root / "school/hongkong"
    grid_base = (
        data_root
        / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
        / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat"
    )
    return {
        "dcca": census / "DCCA_21C.xlsx",
        "retention": school / "processed/student_school_od_2022/dcca_fixed_link_retention.csv",
        "crosswalk": school / "processed/student_school_od_2022/dcca_study_area_crosswalk.parquet",
        "tcs": school / "tcs2022_school_od_csv_revised_bundle/tcs2022_school_od_district_inputs.csv",
        "grid": grid_base / "population_age_sex_grid_features.csv",
    }


def largest_remainder(values: np.ndarray, total: int) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype="float64"), nan=0.0, posinf=0.0, neginf=0.0)
    values = np.maximum(values, 0.0)
    if total <= 0:
        return np.zeros(len(values), dtype="int64")
    if values.sum() <= 0:
        values = np.ones(len(values), dtype="float64")
    quotas = values / values.sum() * int(total)
    result = np.floor(quotas).astype("int64")
    remainder = int(total - result.sum())
    if remainder:
        order = np.lexsort((np.arange(len(values)), -(quotas - result)))
        result[order[:remainder]] += 1
    return result


def checked_numeric(frame: pd.DataFrame, columns: tuple[str, ...] | list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        text = result[column].astype(str).str.strip()
        if text.str.contains(r"\*\*", regex=True).any():
            raise ValueError(f"Suppressed high-error Census values found in {column}")
        result[column] = pd.to_numeric(result[column].where(text.ne("-"), 0), errors="coerce").fillna(0.0)
    return result


def logit(rate: np.ndarray | float) -> np.ndarray:
    value = np.clip(np.asarray(rate, dtype="float64"), 1e-6, 1 - 1e-6)
    return np.log(value / (1 - value))


def expit(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype="float64")
    return np.where(value >= 0, 1 / (1 + np.exp(-value)), np.exp(value) / (1 + np.exp(value)))


def assign_ordered_categories(counts: np.ndarray, score: np.ndarray) -> np.ndarray:
    categories = np.repeat(np.arange(1, len(counts) + 1, dtype="int8"), counts)
    if len(categories) != len(score):
        raise ValueError("Controlled category count does not match household count")
    result = np.empty(len(score), dtype="int8")
    result[np.argsort(score, kind="stable")] = categories
    return result


def draw_income(band: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    bounds = {
        1: (2_000, 5_999),
        2: (6_000, 9_999),
        3: (10_000, 19_999),
        4: (20_000, 29_999),
        5: (30_000, 39_999),
        6: (40_000, 59_999),
    }
    income = np.zeros(len(band), dtype="int32")
    for code, (low, high) in bounds.items():
        mask = band == code
        income[mask] = rng.integers(low, high + 1, size=int(mask.sum()), dtype="int32")
    mask = band == 7
    if mask.any():
        draws = rng.lognormal(mean=math.log(82_000), sigma=0.55, size=int(mask.sum()))
        income[mask] = np.clip(np.rint(draws), 60_000, 400_000).astype("int32")
    return income


def tcs_income_band(income: np.ndarray) -> np.ndarray:
    return np.select(
        [income < 10_000, income < 20_000, income < 30_000, income < 50_000],
        [1, 2, 3, 4],
        default=5,
    ).astype("int8")


def adjust_six_plus_sizes(sizes: np.ndarray, desired_people: int, rng: np.random.Generator) -> np.ndarray:
    result = sizes.copy()
    delta = int(desired_people - result.sum())
    if delta <= 0:
        return result
    candidates = np.flatnonzero(result >= 6)
    if not len(candidates):
        return result
    candidates = rng.permutation(candidates)
    cursor = 0
    while delta > 0:
        idx = int(candidates[cursor % len(candidates)])
        result[idx] += 1
        cursor += 1
        delta -= 1
    return result


def load_inputs(paths: dict[str, Path], sample_rate: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)
    dcca = pd.read_excel(paths["dcca"], sheet_name="DCCA", header=4)
    dcca = dcca[pd.to_numeric(dcca["dcca"], errors="coerce").notna()].copy()
    dcca["dcca"] = pd.to_numeric(dcca["dcca"]).astype("int64")
    numeric = ["dc", "dh", "adhz", "pop_m", "pop_f", *SIZE_COLUMNS, *INCOME_COLUMNS, *HOUSING_COLUMNS, *AGE_COLUMNS]
    dcca = checked_numeric(dcca, numeric)
    retention = pd.read_csv(paths["retention"])
    retention["dcca"] = pd.to_numeric(retention["dcca"]).astype("int64")
    dcca = dcca.merge(
        retention[["dcca", "fixed_link_population_ratio", "fixed_link_status"]],
        on="dcca",
        how="inner",
        validate="one_to_one",
    )
    if len(dcca) != 452 or dcca["fixed_link_population_ratio"].isna().any():
        raise ValueError(f"Expected 452 DCCAs with fixed-link retention ratios, got {len(dcca)}")
    expected = dcca["dh"].to_numpy() * dcca["fixed_link_population_ratio"].to_numpy() * sample_rate
    total = int(round(expected.sum()))
    dcca["synthetic_households"] = largest_remainder(expected, total)

    crosswalk = pd.read_parquet(
        paths["crosswalk"],
        columns=["grid_id", "origin_unit_id", "dcca", "tcs_zone", "grid_piece_share", "raw_school_age"],
    )
    crosswalk["dcca"] = pd.to_numeric(crosswalk["dcca"]).astype("int64")
    grid = pd.read_csv(paths["grid"], usecols=["grid_id", "locations", "population", "area_km2"])
    crosswalk = crosswalk.merge(grid[["grid_id", "population"]], on="grid_id", validate="many_to_one")
    crosswalk["location_weight"] = crosswalk["grid_piece_share"].clip(lower=0) * crosswalk["population"].clip(lower=0)
    tcs = pd.read_csv(paths["tcs"])
    if set(tcs["district_id"].astype(int)) != set(range(1, 27)):
        raise ValueError("TCS vehicle control must contain districts 1-26")
    return dcca, crosswalk, grid, tcs


def synthesize_households(
    dcca: pd.DataFrame,
    crosswalk: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    chunks: list[pd.DataFrame] = []
    controls: list[dict[str, object]] = []
    next_index = 0
    by_dcca = {int(code): group.reset_index(drop=True) for code, group in crosswalk.groupby("dcca", sort=False)}
    for row in dcca.itertuples(index=False):
        n = int(row.synthetic_households)
        if n <= 0:
            continue
        code = int(row.dcca)
        location = by_dcca.get(code)
        if location is None or location.empty:
            raise ValueError(f"No retained grid crosswalk for DCCA {code} with {n} households")
        weights = location["location_weight"].to_numpy(dtype="float64")
        if weights.sum() <= 0:
            weights = location["raw_school_age"].to_numpy(dtype="float64")
        if weights.sum() <= 0:
            weights = location["grid_piece_share"].to_numpy(dtype="float64")
        if weights.sum() <= 0:
            weights = np.ones(len(location), dtype="float64")
        picked = rng.choice(len(location), size=n, replace=True, p=weights / weights.sum())

        latent = rng.normal(size=n)
        size_counts = largest_remainder(np.asarray([getattr(row, c) for c in SIZE_COLUMNS]), n)
        sizes = assign_ordered_categories(size_counts, latent * 0.25 + rng.normal(size=n))
        desired_people = max(int(sizes.sum()), int(round(n * float(row.adhz))))
        sizes = adjust_six_plus_sizes(sizes, desired_people, rng)

        income_counts = largest_remainder(np.asarray([getattr(row, c) for c in INCOME_COLUMNS]), n)
        income_band = assign_ordered_categories(income_counts, latent + rng.normal(scale=0.55, size=n))
        income = draw_income(income_band, rng)

        housing_counts = largest_remainder(np.asarray([getattr(row, c) for c in HOUSING_COLUMNS]), n)
        housing_rank = np.asarray([0.0, 0.55, 1.0, 0.25, -0.25])
        raw_housing = assign_ordered_categories(housing_counts[np.argsort(housing_rank)], latent + rng.normal(scale=0.7, size=n))
        housing_order = np.argsort(housing_rank) + 1
        housing = housing_order[raw_housing - 1].astype("int8")

        selected = location.iloc[picked]
        frame = pd.DataFrame(
            {
                "household_index": np.arange(next_index, next_index + n, dtype="int64"),
                "dcca": np.full(n, code, dtype="int16"),
                "dc": np.full(n, int(row.dc), dtype="int8"),
                "grid_id": selected["grid_id"].to_numpy(dtype="int16"),
                "origin_unit_id": selected["origin_unit_id"].to_numpy(dtype="int32"),
                "tcs_zone": selected["tcs_zone"].to_numpy(dtype="int8"),
                "household_size": sizes.astype("int8"),
                "income_band_dcca": income_band,
                "monthly_household_income_hkd": income,
                "income_band_tcs": tcs_income_band(income),
                "housing_code": housing,
            }
        )
        chunks.append(frame)
        next_index += n
        controls.append(
            {
                "dcca": code,
                "dcca_eng": row.dcca_eng,
                "dc": int(row.dc),
                "dc_eng": row.dc_eng,
                "retention_ratio": float(row.fixed_link_population_ratio),
                "target_households": n,
                "actual_households": n,
                "target_people_from_average": int(round(n * float(row.adhz))),
                "actual_people": int(sizes.sum()),
                "target_average_household_size": float(row.adhz),
                "actual_average_household_size": float(sizes.mean()),
            }
        )
    households = pd.concat(chunks, ignore_index=True)
    households["private_vehicle_prior_probability"] = np.float32(0)
    households["private_car_count"] = np.int8(0)
    households["motorcycle_count"] = np.int8(0)
    return households, pd.DataFrame(controls)


def select_top(indices: np.ndarray, count: int, score: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    if count <= 0:
        return np.empty(0, dtype="int64")
    if count > len(indices):
        raise ValueError(f"Cannot select {count} households from {len(indices)} candidates")
    jitter = rng.gumbel(size=len(indices))
    order = np.argpartition(score[indices] + jitter, -count)[-count:]
    return indices[order]


def assign_vehicle_counts(
    households: pd.DataFrame,
    tcs: pd.DataFrame,
    shrinkage: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    housing_rate = households["housing_code"].map(TCS_HOUSING_RATES).to_numpy(dtype="float64")
    size_rate = households["household_size"].clip(upper=5).map(TCS_SIZE_RATES).to_numpy(dtype="float64")
    income_rate = households["income_band_tcs"].map(TCS_INCOME_RATES).to_numpy(dtype="float64")
    effect = shrinkage * (
        logit(housing_rate) - logit(OVERALL_PV_RATE)
        + logit(size_rate) - logit(OVERALL_PV_RATE)
        + logit(income_rate) - logit(OVERALL_PV_RATE)
    )
    validation: list[dict[str, object]] = []
    tcs_lookup = tcs.set_index("district_id")
    for zone in sorted(households["tcs_zone"].unique()):
        row = tcs_lookup.loc[int(zone)]
        indices = np.flatnonzero(households["tcs_zone"].to_numpy() == zone)
        n = len(indices)
        zone_rate = float(row.private_vehicle_available_pct_households) / 100
        score = np.full(n, logit(zone_rate), dtype="float64") + effect[indices]
        households.loc[indices, "private_vehicle_prior_probability"] = expit(score).astype("float32")
        global_score = np.full(len(households), -np.inf, dtype="float64")
        global_score[indices] = score

        any_target = int(round(n * float(row.private_vehicle_available_pct_households) / 100))
        pc_target_raw = int(round(n * float(row.private_car_available_pct_households) / 100))
        mc_target_raw = int(round(n * float(row.motorcycle_available_pct_households) / 100))
        pc_target = pc_target_raw
        mc_target = mc_target_raw
        if pc_target + mc_target < any_target:
            pc_target += any_target - pc_target - mc_target
        if max(pc_target, mc_target) > any_target:
            if pc_target >= mc_target:
                pc_target = any_target
            else:
                mc_target = any_target
        overlap = pc_target + mc_target - any_target
        if not 0 <= overlap <= min(pc_target, mc_target):
            raise ValueError(f"Rounded A.4 controls are infeasible in TCS zone {zone}")
        both_target = overlap
        pc_only_target = pc_target - overlap
        mc_only_target = mc_target - overlap

        any_selected = select_top(indices, any_target, global_score, rng)
        both = select_top(any_selected, both_target, global_score, rng)
        remaining = np.setdiff1d(any_selected, both, assume_unique=False)
        pc_only = select_top(remaining, pc_only_target, global_score, rng)
        mc_only = np.setdiff1d(remaining, pc_only, assume_unique=False)
        if len(mc_only) != mc_only_target:
            raise ValueError(f"Motorcycle-only assignment failed in TCS zone {zone}")
        pc_households = np.concatenate([both, pc_only])
        mc_households = np.concatenate([both, mc_only])

        pc_raw = np.asarray(
            [row.private_car_1_pct_households, row.private_car_2_pct_households, row.private_car_more_than_2_pct_households],
            dtype="float64",
        )
        pc_counts = largest_remainder(pc_raw, pc_target)
        pc_order = pc_households[np.argsort(global_score[pc_households] + rng.gumbel(size=pc_target))]
        cursor = 0
        for count, number in zip((1, 2, 3), pc_counts):
            chosen = pc_order[cursor : cursor + int(number)]
            households.loc[chosen, "private_car_count"] = np.int8(count)
            cursor += int(number)

        mc_raw = np.asarray(
            [row.motorcycle_1_pct_households, row.motorcycle_2plus_pct_households], dtype="float64"
        )
        mc_counts = largest_remainder(mc_raw, mc_target)
        mc_order = mc_households[np.argsort(global_score[mc_households] + rng.gumbel(size=mc_target))]
        cursor = 0
        for count, number in zip((1, 2), mc_counts):
            chosen = mc_order[cursor : cursor + int(number)]
            households.loc[chosen, "motorcycle_count"] = np.int8(count)
            cursor += int(number)

        actual_pc = int((households.loc[indices, "private_car_count"] > 0).sum())
        actual_mc = int((households.loc[indices, "motorcycle_count"] > 0).sum())
        actual_any = int(
            ((households.loc[indices, "private_car_count"] + households.loc[indices, "motorcycle_count"]) > 0).sum()
        )
        validation.append(
            {
                "tcs_zone": int(zone),
                "district_name": row.district_name,
                "synthetic_households": n,
                "target_pv_available_households": any_target,
                "actual_pv_available_households": actual_any,
                "pv_household_error": actual_any - any_target,
                "target_pv_available_pct": float(row.private_vehicle_available_pct_households),
                "actual_pv_available_pct": 100 * actual_any / n,
                "target_pc_available_households": pc_target,
                "independently_rounded_pc_available_households": pc_target_raw,
                "actual_pc_available_households": actual_pc,
                "target_mc_available_households": mc_target,
                "independently_rounded_mc_available_households": mc_target_raw,
                "actual_mc_available_households": actual_mc,
                "pc_mc_integer_reconciliation_households": abs(pc_target - pc_target_raw) + abs(mc_target - mc_target_raw),
                "target_pc_1_households": int(pc_counts[0]),
                "actual_pc_1_households": int((households.loc[indices, "private_car_count"] == 1).sum()),
                "target_pc_2_households": int(pc_counts[1]),
                "actual_pc_2_households": int((households.loc[indices, "private_car_count"] == 2).sum()),
                "target_pc_3plus_households": int(pc_counts[2]),
                "actual_pc_3plus_households": int((households.loc[indices, "private_car_count"] == 3).sum()),
                "target_mc_1_households": int(mc_counts[0]),
                "actual_mc_1_households": int((households.loc[indices, "motorcycle_count"] == 1).sum()),
                "target_mc_2plus_households": int(mc_counts[1]),
                "actual_mc_2plus_households": int((households.loc[indices, "motorcycle_count"] == 2).sum()),
            }
        )
    households["private_vehicle_count"] = (
        households["private_car_count"] + households["motorcycle_count"]
    ).astype("int8")
    return pd.DataFrame(validation)


def draw_ages(age_counts: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    bins = np.repeat(np.arange(1, 6, dtype="int8"), age_counts)
    ages = np.empty(len(bins), dtype="int8")
    ranges = {1: (0, 14), 2: (15, 24), 3: (25, 44), 4: (45, 64), 5: (65, 95)}
    for code, (low, high) in ranges.items():
        mask = bins == code
        ages[mask] = rng.integers(low, high + 1, size=int(mask.sum()), dtype="int8")
    order = rng.permutation(len(ages))
    return bins[order], ages[order]


def ensure_adult_reference(ages: np.ndarray, household_start: np.ndarray) -> None:
    bad = household_start[ages[household_start] < 18]
    if not len(bad):
        return
    is_head = np.zeros(len(ages), dtype=bool)
    is_head[household_start] = True
    donors = np.flatnonzero((ages >= 25) & ~is_head)
    if len(donors) < len(bad):
        donors = np.flatnonzero((ages >= 18) & ~is_head)
    if len(donors) < len(bad):
        raise ValueError("Not enough adult members to assign an adult household reference person")
    chosen = donors[: len(bad)]
    ages[bad], ages[chosen] = ages[chosen].copy(), ages[bad].copy()


def parquet_writer(path: Path, compression: str = "zstd"):
    state: dict[str, pq.ParquetWriter | None] = {"writer": None}

    def write(frame: pd.DataFrame) -> None:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if state["writer"] is None:
            state["writer"] = pq.ParquetWriter(path, table.schema, compression=compression, use_dictionary=True)
        state["writer"].write_table(table)

    def close() -> None:
        if state["writer"] is not None:
            state["writer"].close()

    return write, close


def write_microdata(
    households: pd.DataFrame,
    dcca: pd.DataFrame,
    tcs: pd.DataFrame,
    out_dir: Path,
    sample_rate: float,
    rng: np.random.Generator,
) -> tuple[int, int, pd.DataFrame, pd.DataFrame]:
    dcca_lookup = dcca.set_index("dcca")
    tcs_names = tcs.set_index("district_id")["district_name"].to_dict()
    household_write, household_close = parquet_writer(out_dir / "synthetic_households.parquet")
    person_write, person_close = parquet_writer(out_dir / "synthetic_persons.parquet")
    vehicle_write, vehicle_close = parquet_writer(out_dir / "synthetic_household_vehicles.parquet")
    person_cursor = 0
    vehicle_cursor = 0
    grid_rows: list[pd.DataFrame] = []
    person_validation_rows: list[dict[str, object]] = []

    for dcca_code, group in households.groupby("dcca", sort=True):
        group = group.copy()
        census = dcca_lookup.loc[int(dcca_code)]
        n_people = int(group["household_size"].sum())
        age_counts = largest_remainder(np.asarray([census[c] for c in AGE_COLUMNS]), n_people)
        age_band, age = draw_ages(age_counts, rng)
        sex_counts = largest_remainder(np.asarray([census.pop_m, census.pop_f]), n_people)
        sex = np.repeat(np.asarray(["M", "F"], dtype=object), sex_counts)
        sex = sex[rng.permutation(n_people)]

        sizes = group["household_size"].to_numpy(dtype="int64")
        hh_local = np.repeat(np.arange(len(group), dtype="int64"), sizes)
        starts = np.r_[0, np.cumsum(sizes)[:-1]]
        member_sequence = np.arange(n_people, dtype="int64") - np.repeat(starts, sizes)
        ensure_adult_reference(age, starts)
        age_band = np.select(
            [age < 15, age < 25, age < 45, age < 65], [1, 2, 3, 4], default=5
        ).astype("int8")
        for code, target in enumerate(age_counts, start=1):
            actual = int((age_band == code).sum())
            person_validation_rows.append(
                {
                    "dcca": int(dcca_code), "dimension": "age_band", "category": code,
                    "target_persons": int(target), "actual_persons": actual, "error": actual - int(target),
                }
            )
        for label, target in zip(("M", "F"), sex_counts):
            actual = int((sex == label).sum())
            person_validation_rows.append(
                {
                    "dcca": int(dcca_code), "dimension": "sex", "category": label,
                    "target_persons": int(target), "actual_persons": actual, "error": actual - int(target),
                }
            )

        relationship = np.full(n_people, "other_member", dtype=object)
        relationship[member_sequence == 0] = "reference_person"
        relationship[(member_sequence == 1) & (age >= 18)] = "partner_or_other_adult"
        relationship[(member_sequence > 0) & (age < 18)] = "child"
        relationship[(member_sequence > 1) & (age >= 18) & (age < 25)] = "adult_child_or_young_adult"
        relationship[(member_sequence > 1) & (age >= 65)] = "older_relative"

        hh_indices = group["household_index"].to_numpy(dtype="int64")
        vehicle_count = group["private_vehicle_count"].to_numpy(dtype="int8")
        private_car_count = group["private_car_count"].to_numpy(dtype="int8")
        motorcycle_count = group["motorcycle_count"].to_numpy(dtype="int8")
        repeated_hh = hh_indices[hh_local]
        assigned_vehicle_count = np.zeros(n_people, dtype="int8")
        vehicle_records: list[dict[str, object]] = []
        for local_hh in np.flatnonzero(vehicle_count > 0):
            first = int(starts[local_hh])
            last = first + int(sizes[local_hh])
            eligible = np.flatnonzero(age[first:last] >= 18) + first
            priority = eligible[np.argsort(np.abs(age[eligible].astype(int) - 45), kind="stable")]
            types = ["private_car"] * int(private_car_count[local_hh])
            types += ["motorcycle"] * int(motorcycle_count[local_hh])
            for slot, vehicle_type in enumerate(types):
                driver_local = int(priority[slot % len(priority)])
                assigned_vehicle_count[driver_local] += 1
                vehicle_records.append(
                    {
                        "vehicle_id": f"hk_vehicle_{vehicle_cursor:07d}",
                        "vehicle_index": vehicle_cursor,
                        "household_id": f"hk_hh_{int(hh_indices[local_hh]):07d}",
                        "household_index": int(hh_indices[local_hh]),
                        "vehicle_type": vehicle_type,
                        "vehicle_sequence": slot,
                        "driver_person_id": f"hk_person_{person_cursor + driver_local:08d}",
                        "driver_person_index": person_cursor + driver_local,
                        "count_class_is_lower_bound": bool(
                            (vehicle_type == "private_car" and int(private_car_count[local_hh]) == 3)
                            or (vehicle_type == "motorcycle" and int(motorcycle_count[local_hh]) == 2)
                        ),
                        "sample_weight": 1.0 / sample_rate,
                    }
                )
                vehicle_cursor += 1

        household_output = pd.DataFrame(
            {
                "household_id": [f"hk_hh_{value:07d}" for value in hh_indices],
                "household_index": hh_indices,
                "dcca": group["dcca"].astype("int16"),
                "dcca_eng": str(census.dcca_eng),
                "dc": group["dc"].astype("int8"),
                "dc_eng": str(census.dc_eng),
                "grid_id": group["grid_id"].astype("int16"),
                "origin_unit_id": group["origin_unit_id"].astype("int32"),
                "tcs_zone": group["tcs_zone"].astype("int8"),
                "tcs_district_name": group["tcs_zone"].map(tcs_names),
                "household_size": group["household_size"].astype("int8"),
                "income_band_dcca": group["income_band_dcca"].map(INCOME_LABELS),
                "monthly_household_income_hkd": group["monthly_household_income_hkd"].astype("int32"),
                "income_band_tcs": group["income_band_tcs"].astype("int8"),
                "housing_type": group["housing_code"].map(HOUSING_LABELS),
                "private_vehicle_prior_probability": group["private_vehicle_prior_probability"].astype("float32"),
                "private_car_count": group["private_car_count"].astype("int8"),
                "motorcycle_count": group["motorcycle_count"].astype("int8"),
                "private_vehicle_count": group["private_vehicle_count"].astype("int8"),
                "private_vehicle_count_category": np.where(
                    group["private_vehicle_count"].eq(0), "0",
                    np.where(group["private_vehicle_count"].eq(1), "1", np.where(group["private_vehicle_count"].eq(2), "2", "3_plus")),
                ),
                "sample_weight": 1.0 / sample_rate,
            }
        )
        household_write(household_output)

        person_indices = np.arange(person_cursor, person_cursor + n_people, dtype="int64")
        person_output = pd.DataFrame(
            {
                "person_id": [f"hk_person_{value:08d}" for value in person_indices],
                "person_index": person_indices,
                "household_id": [f"hk_hh_{value:07d}" for value in repeated_hh],
                "household_index": repeated_hh,
                "member_sequence": member_sequence.astype("int8"),
                "relationship_role": relationship,
                "age": age,
                "age_band_census": age_band,
                "sex": sex,
                "dcca": group["dcca"].to_numpy()[hh_local].astype("int16"),
                "grid_id": group["grid_id"].to_numpy()[hh_local].astype("int16"),
                "tcs_zone": group["tcs_zone"].to_numpy()[hh_local].astype("int8"),
                "household_private_vehicle_count": vehicle_count[hh_local],
                "potential_household_vehicle_access": ((age >= 18) & (vehicle_count[hh_local] > 0)),
                "is_designated_driver": assigned_vehicle_count > 0,
                "assigned_vehicle_count": assigned_vehicle_count,
                "sample_weight": 1.0 / sample_rate,
            }
        )
        person_write(person_output)
        if vehicle_records:
            vehicle_write(pd.DataFrame(vehicle_records))

        grid_rows.append(
            household_output.groupby(["grid_id", "tcs_zone"], as_index=False).agg(
                households=("household_index", "size"),
                household_members=("household_size", "sum"),
                pv_available_households=("private_vehicle_count", lambda s: int((s > 0).sum())),
                private_cars=("private_car_count", "sum"),
                motorcycles=("motorcycle_count", "sum"),
            )
        )
        person_cursor += n_people

    household_close()
    person_close()
    vehicle_close()
    grid_summary = pd.concat(grid_rows, ignore_index=True).groupby(["grid_id", "tcs_zone"], as_index=False).sum()
    return person_cursor, vehicle_cursor, grid_summary, pd.DataFrame(person_validation_rows)


def build_category_validation(households: pd.DataFrame, dcca: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    lookup = dcca.set_index("dcca")
    for dcca_code, group in households.groupby("dcca", sort=True):
        source = lookup.loc[int(dcca_code)]
        n = len(group)
        for dimension, columns, actual_column in (
            ("household_size", SIZE_COLUMNS, "household_size"),
            ("income_band_dcca", INCOME_COLUMNS, "income_band_dcca"),
            ("housing_type", HOUSING_COLUMNS, "housing_code"),
        ):
            targets = largest_remainder(np.asarray([source[c] for c in columns]), n)
            for category, target in enumerate(targets, start=1):
                actual = int((group[actual_column] == category).sum())
                if dimension == "household_size" and category == 6:
                    actual = int((group[actual_column] >= 6).sum())
                rows.append(
                    {
                        "dcca": int(dcca_code),
                        "dimension": dimension,
                        "category": category,
                        "target_households": int(target),
                        "actual_households": actual,
                        "error": actual - int(target),
                    }
                )
    return pd.DataFrame(rows)


def build_tcs_characteristic_validation(households: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    specifications = (
        (
            "housing_type",
            households["housing_code"],
            {
                1: ("public_rental", 5.5),
                2: ("subsidised_home_ownership", 12.1),
                3: ("private_permanent", 25.1),
                4: ("non_domestic", np.nan),
                5: ("temporary", np.nan),
            },
        ),
        (
            "monthly_household_income",
            households["income_band_tcs"],
            {
                1: ("less_than_10000", 3.7),
                2: ("10000_19999", 5.9),
                3: ("20000_29999", 10.6),
                4: ("30000_49999", 17.0),
                5: ("50000_plus", 38.1),
            },
        ),
        (
            "household_size",
            households["household_size"].clip(upper=5),
            {
                1: ("1", 7.0),
                2: ("2", 13.9),
                3: ("3", 18.2),
                4: ("4", 25.0),
                5: ("5_plus", 34.7),
            },
        ),
    )
    available = households["private_vehicle_count"].to_numpy() > 0
    for dimension, codes, labels in specifications:
        code_values = codes.to_numpy()
        for code, (label, target) in labels.items():
            mask = code_values == code
            total = int(mask.sum())
            actual = int((available & mask).sum())
            actual_rate = 100 * actual / total if total else np.nan
            rows.append(
                {
                    "dimension": dimension,
                    "category": label,
                    "households": total,
                    "pv_available_households": actual,
                    "tcs2022_table_4_2_pv_available_pct": target,
                    "synthetic_pv_available_pct": actual_rate,
                    "difference_percentage_points": actual_rate - target if np.isfinite(target) else np.nan,
                    "constraint_role": "ranking_prior_not_hard_margin" if np.isfinite(target) else "unpublished_use_overall_prior",
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    if not 0 < args.sample_rate <= 1:
        raise ValueError("--sample-rate must be in (0, 1]")
    if not 0 <= args.effect_shrinkage <= 1:
        raise ValueError("--effect-shrinkage must be in [0, 1]")
    paths = input_paths(args.data_root)
    out_dir = args.out_dir or args.data_root / "matsim_agents/hongkong/synthetic_households_tcs2022"
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    dcca, crosswalk, grid, tcs = load_inputs(paths, args.sample_rate)
    households, dcca_validation = synthesize_households(dcca, crosswalk, rng)
    category_validation = build_category_validation(households, dcca)
    vehicle_validation = assign_vehicle_counts(households, tcs, args.effect_shrinkage, rng)
    characteristic_validation = build_tcs_characteristic_validation(households)
    person_count, vehicle_count, grid_summary, person_validation = write_microdata(
        households, dcca, tcs, out_dir, args.sample_rate, rng
    )
    grid_summary = grid_summary.merge(grid, on="grid_id", how="left", validate="many_to_one")
    grid_summary["synthetic_household_population_to_worldpop_ratio"] = np.divide(
        grid_summary["household_members"],
        grid_summary["population"],
        out=np.full(len(grid_summary), np.nan),
        where=grid_summary["population"].to_numpy() > 0,
    )

    tcs_controls = tcs[
        [
            "district_id", "district_name", "households_reported",
            "private_car_1_pct_households", "private_car_2_pct_households",
            "private_car_more_than_2_pct_households", "private_car_available_pct_households",
            "motorcycle_1_pct_households", "motorcycle_2plus_pct_households",
            "motorcycle_available_pct_households", "private_vehicle_available_pct_households",
        ]
    ].copy()
    tcs_controls.to_csv(out_dir / "tcs2022_table_a4_vehicle_controls.csv", index=False, encoding="utf-8-sig")
    dcca_validation.to_csv(out_dir / "dcca_household_totals_validation.csv", index=False, encoding="utf-8-sig")
    category_validation.to_csv(out_dir / "dcca_household_marginal_validation.csv", index=False, encoding="utf-8-sig")
    person_validation.to_csv(out_dir / "dcca_person_marginal_validation.csv", index=False, encoding="utf-8-sig")
    vehicle_validation.to_csv(out_dir / "tcs26_vehicle_validation.csv", index=False, encoding="utf-8-sig")
    characteristic_validation.to_csv(
        out_dir / "tcs2022_table_4_2_household_characteristic_validation.csv", index=False, encoding="utf-8-sig"
    )
    grid_summary.to_csv(out_dir / "grid_household_population_summary.csv", index=False, encoding="utf-8-sig")

    maximum_vehicle_error = int(
        vehicle_validation[
            [
                "pv_household_error",
                "target_pc_available_households",
                "actual_pc_available_households",
                "target_mc_available_households",
                "actual_mc_available_households",
            ]
        ]
        .assign(
            pc_error=lambda x: x.actual_pc_available_households - x.target_pc_available_households,
            mc_error=lambda x: x.actual_mc_available_households - x.target_mc_available_households,
        )[["pv_household_error", "pc_error", "mc_error"]]
        .abs()
        .to_numpy()
        .max()
    )
    summary = {
        "scenario": "hong_kong_synthetic_households_tcs2022",
        "seed": args.seed,
        "sample_rate": args.sample_rate,
        "sample_weight": 1.0 / args.sample_rate,
        "effect_shrinkage": args.effect_shrinkage,
        "households": int(len(households)),
        "persons": int(person_count),
        "persons_target_from_rounded_dcca_average_household_size": int(
            dcca_validation["target_people_from_average"].sum()
        ),
        "dcca_average_household_size_person_wape": float(
            (dcca_validation["actual_people"] - dcca_validation["target_people_from_average"]).abs().sum()
            / dcca_validation["target_people_from_average"].sum()
        ),
        "vehicles_representative_lower_bound": int(vehicle_count),
        "pv_available_households": int((households["private_vehicle_count"] > 0).sum()),
        "private_cars_representative_lower_bound": int(households["private_car_count"].sum()),
        "motorcycles_representative_lower_bound": int(households["motorcycle_count"].sum()),
        "tcs26_districts": int(households["tcs_zone"].nunique()),
        "maximum_tcs26_vehicle_household_control_error": maximum_vehicle_error,
        "maximum_dcca_marginal_control_error": int(category_validation["error"].abs().max()),
        "maximum_dcca_person_marginal_control_error": int(person_validation["error"].abs().max()),
        "adult_reference_person_check": True,
        "three_plus_private_cars_represented_as": 3,
        "two_plus_motorcycles_represented_as": 2,
        "vehicle_access_interpretation": "potential access for adult household members; designated drivers are synthetic, not observed licence holders",
        "source_years": {"census_households": 2021, "tcs_vehicle_controls": 2022},
        "outputs": {
            "households": str(out_dir / "synthetic_households.parquet"),
            "persons": str(out_dir / "synthetic_persons.parquet"),
            "vehicles": str(out_dir / "synthetic_household_vehicles.parquet"),
        },
    }
    (out_dir / "synthetic_household_generation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
