from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = Path(
    r"D:\Program Files\hong_kong_public_transport_vehicle_capacity.csv"
)
DEFAULT_SNAPSHOT_NAMES = [
    "20260720T102416Z",
    "20260722T034716Z",
    "20260722T055352Z",
]

SOURCE_COLUMNS = {
    "交通方式": "mode_name",
    "营办商": "operator_name",
    "系统或服务": "system_or_service",
    "车辆大类": "vehicle_class",
    "车型或车卡类型": "vehicle_or_car_type",
    "容量原文": "capacity_raw",
    "座位数": "source_seats",
    "站位数": "source_standing",
    "总容量下限": "source_capacity_min",
    "总容量上限": "source_capacity_max",
    "轮椅位数量": "wheelchair_places",
    "车辆数量原文": "fleet_count_raw",
    "车辆数量": "fleet_count",
    "容量口径": "capacity_basis",
    "统计日期": "statistics_date",
    "来源网页标题": "source_page_title",
    "来源网址": "source_url",
    "备注": "notes",
}

MODE_CODES = {
    "专营巴士": "franchised_bus",
    "公共小巴": "public_light_bus",
    "港铁巴士": "mtr_bus",
    "港铁重铁": "mtr_heavy_rail",
    "轻铁": "light_rail",
    "高速铁路": "high_speed_rail",
    "电车": "tram",
    "渡轮": "ferry",
}

BUS_COMPANY_TO_TYPE = {
    "KMB": "bus_kmb_fleet_weighted",
    "CTB": "bus_citybus_fleet_weighted",
    "NLB": "bus_nlb_fleet_weighted",
    "LWB": "bus_lwb_fleet_weighted",
    "MTR": "bus_mtr_fleet_weighted",
    "LRTFeeder": "bus_mtr_fleet_weighted",
    "KMB+CTB": "bus_kmb_citybus_blended",
    "LWB+CTB": "bus_lwb_citybus_blended",
}

MTR_LINE_TO_TYPE = {
    "KTL": "mtr_urban_8car_fleet_weighted",
    "TWL": "mtr_urban_8car_fleet_weighted",
    "ISL": "mtr_urban_8car_fleet_weighted",
    "TKL": "mtr_urban_8car_fleet_weighted",
    "SIL": "mtr_sil_3car_fleet_weighted",
    "DRL": "mtr_drl_4car_fleet_weighted",
    "TCL": "mtr_tcl_8car_fleet_weighted",
    "AEL": "mtr_ael_8car_including_luggage",
    "EAL": "mtr_eal_9car_fleet_weighted",
    "TML": "mtr_tml_8car_fleet_weighted",
}

TYPE_COLUMNS = [
    "vehicle_type_id",
    "mode",
    "operator",
    "system_or_lines",
    "model_seats",
    "model_standing",
    "model_total_capacity",
    "capacity_selection_method",
    "seat_standing_method",
    "capacity_confidence",
    "source_record_count",
    "source_fleet_count",
    "source_trainset_count",
    "cars_per_train",
    "length_m",
    "width_m",
    "access_time_s_per_person",
    "egress_time_s_per_person",
    "door_operation",
    "pce",
    "physical_parameters_status",
    "formation_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize Hong Kong vehicle capacities and build MATSim vehicle "
            "types plus route/departure assignment tables."
        )
    )
    parser.add_argument("--capacity-csv", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--route-qa", type=Path)
    parser.add_argument("--timetable-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        action="append",
        help="MTR/LRT real-time snapshot directory; repeat for multiple snapshots.",
    )
    parser.add_argument(
        "--complete-inference",
        action="store_true",
        help=(
            "Fill every route capacity with auditable proxies and allocate TML "
            "fleet variants plus LRT one/two-car consists to departures."
        ),
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    for attempt in range(4):
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.5)
    raise RuntimeError(f"Could not hash {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def normalized_source(source: Path) -> pd.DataFrame:
    raw = pd.read_csv(source)
    missing = sorted(set(SOURCE_COLUMNS) - set(raw.columns))
    if missing:
        raise ValueError(f"Capacity CSV is missing columns: {missing}")
    if len(raw) != 169:
        raise ValueError(f"Expected 169 capacity records, found {len(raw)}")

    df = raw.rename(columns=SOURCE_COLUMNS)[list(SOURCE_COLUMNS.values())].copy()
    df.insert(0, "source_record_id", [f"hkvc_{i:04d}" for i in range(1, len(df) + 1)])
    df.insert(2, "mode", df["mode_name"].map(MODE_CODES))
    if df["mode"].isna().any():
        unknown = sorted(df.loc[df["mode"].isna(), "mode_name"].unique())
        raise ValueError(f"Unknown transport modes: {unknown}")

    numeric = [
        "source_seats",
        "source_standing",
        "source_capacity_min",
        "source_capacity_max",
        "wheelchair_places",
        "fleet_count",
    ]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["is_passenger_vehicle"] = ~df["capacity_basis"].str.contains(
        "非载客|无乘客容量", na=False
    )
    df["is_per_vehicle_capacity"] = ~df["capacity_basis"].str.contains(
        "整支船队总载客量", na=False
    )
    df["usable_as_vehicle_capacity"] = (
        df["is_passenger_vehicle"]
        & df["is_per_vehicle_capacity"]
        & df["source_capacity_min"].notna()
        & df["source_capacity_max"].notna()
    )
    df["model_total_capacity"] = (
        (df["source_capacity_min"] + df["source_capacity_max"]) / 2.0
    ).round()
    df.loc[~df["usable_as_vehicle_capacity"], "model_total_capacity"] = math.nan

    df["model_seats"] = math.nan
    df["model_standing"] = math.nan
    df["seat_standing_method"] = "not_applicable"

    known = (
        df["usable_as_vehicle_capacity"]
        & df["source_seats"].notna()
        & df["source_standing"].notna()
    )
    df.loc[known, "model_seats"] = df.loc[known, "source_seats"]
    df.loc[known, "model_standing"] = df.loc[known, "source_standing"]
    df.loc[known, "seat_standing_method"] = "source_exact"

    # The table gives only licensed total capacity for these modes. The split is
    # explicitly provisional so total capacity is preserved without hiding the gap.
    split_rules = [
        ("franchised_bus", "双层", 0.65, "assumed_double_deck_bus_65pct_seated"),
        ("franchised_bus", "单层", 0.55, "assumed_single_deck_bus_55pct_seated"),
        ("mtr_bus", "双层", 0.65, "assumed_double_deck_bus_65pct_seated"),
        ("mtr_bus", "单层", 0.55, "assumed_single_deck_bus_55pct_seated"),
        ("light_rail", None, 0.25, "assumed_light_rail_25pct_seated"),
        ("tram", None, 0.45, "assumed_tram_45pct_seated"),
        ("ferry", None, 1.00, "total_as_seated_proxy"),
        ("high_speed_rail", None, 1.00, "reserved_capacity_as_seats"),
    ]
    for mode, class_text, seated_share, method in split_rules:
        mask = df["usable_as_vehicle_capacity"] & df["mode"].eq(mode)
        if class_text:
            mask &= df["vehicle_class"].str.contains(class_text, na=False)
        mask &= df["model_seats"].isna()
        seats = (df.loc[mask, "model_total_capacity"] * seated_share).round()
        df.loc[mask, "model_seats"] = seats
        df.loc[mask, "model_standing"] = (
            df.loc[mask, "model_total_capacity"] - seats
        )
        df.loc[mask, "seat_standing_method"] = method

    unresolved = df["usable_as_vehicle_capacity"] & df["model_seats"].isna()
    if unresolved.any():
        labels = df.loc[unresolved, ["mode_name", "vehicle_class"]].drop_duplicates()
        raise ValueError(f"No seat/standing rule for:\n{labels.to_string(index=False)}")

    df["capacity_selection_method"] = "exact_total"
    ranged = df["source_capacity_min"].ne(df["source_capacity_max"])
    df.loc[ranged & df["usable_as_vehicle_capacity"], "capacity_selection_method"] = (
        "midpoint_of_source_range"
    )
    df.loc[~df["usable_as_vehicle_capacity"], "capacity_selection_method"] = (
        "not_usable_per_vehicle"
    )
    df["capacity_quality"] = "total_only_split_provisional"
    df.loc[known, "capacity_quality"] = "seats_and_standing_source_exact"
    df.loc[~df["usable_as_vehicle_capacity"], "capacity_quality"] = (
        "excluded_nonpassenger_or_aggregate"
    )
    df["needs_correction"] = (
        df["usable_as_vehicle_capacity"]
        & df["seat_standing_method"].ne("source_exact")
    ) | ~df["usable_as_vehicle_capacity"]
    return df


def round_parts(total: float, seats: float) -> tuple[int, int, int]:
    model_total = int(round(total))
    model_seats = min(model_total, max(0, int(round(seats))))
    return model_seats, model_total - model_seats, model_total


def physical_defaults(mode: str, length_m: float) -> dict[str, Any]:
    values = {
        "bus": (2.55, 0.8, 0.6, "parallel", 2.5),
        "minibus": (2.10, 1.0, 0.8, "serial", 1.5),
        "mtr": (3.10, 0.35, 0.35, "parallel", 0.0),
        "lrt": (2.65, 0.5, 0.5, "parallel", 0.0),
        "tram": (2.00, 0.8, 0.7, "parallel", 0.0),
        "hsr": (3.36, 0.5, 0.5, "parallel", 0.0),
    }
    width, access, egress, doors, pce = values[mode]
    return {
        "length_m": length_m,
        "width_m": width,
        "access_time_s_per_person": access,
        "egress_time_s_per_person": egress,
        "door_operation": doors,
        "pce": pce,
        "physical_parameters_status": "provisional_mode_default",
    }


def weighted_type(
    source: pd.DataFrame,
    *,
    vehicle_type_id: str,
    mode: str,
    operator: str,
    system_or_lines: str,
    length_m: float,
    confidence: str = "medium",
) -> dict[str, Any]:
    usable = source[source["usable_as_vehicle_capacity"]].copy()
    if usable.empty:
        raise ValueError(f"No usable records for {vehicle_type_id}")
    weights = usable["fleet_count"].fillna(1.0)
    total = (usable["model_total_capacity"] * weights).sum() / weights.sum()
    seats = (usable["model_seats"] * weights).sum() / weights.sum()
    model_seats, model_standing, model_total = round_parts(total, seats)
    methods = sorted(usable["seat_standing_method"].unique())
    result = {
        "vehicle_type_id": vehicle_type_id,
        "mode": mode,
        "operator": operator,
        "system_or_lines": system_or_lines,
        "model_seats": model_seats,
        "model_standing": model_standing,
        "model_total_capacity": model_total,
        "capacity_selection_method": "fleet_count_weighted_source_midpoint",
        "seat_standing_method": "+".join(methods),
        "capacity_confidence": confidence,
        "source_record_count": int(len(usable)),
        "source_fleet_count": float(usable["fleet_count"].sum())
        if usable["fleet_count"].notna().any()
        else math.nan,
        "source_trainset_count": math.nan,
        "cars_per_train": math.nan,
        "formation_note": "Representative operator fleet type; route-specific allocation unknown.",
    }
    result.update(physical_defaults(mode, length_m))
    return result


def blended_type(
    types: list[dict[str, Any]],
    *,
    vehicle_type_id: str,
    operator: str,
) -> dict[str, Any]:
    weights = [float(item["source_fleet_count"]) for item in types]
    total_weight = sum(weights)
    total = sum(item["model_total_capacity"] * w for item, w in zip(types, weights)) / total_weight
    seats = sum(item["model_seats"] * w for item, w in zip(types, weights)) / total_weight
    model_seats, model_standing, model_total = round_parts(total, seats)
    result = {
        "vehicle_type_id": vehicle_type_id,
        "mode": "bus",
        "operator": operator,
        "system_or_lines": "jointly operated franchised bus routes",
        "model_seats": model_seats,
        "model_standing": model_standing,
        "model_total_capacity": model_total,
        "capacity_selection_method": "operator_fleet_count_weighted_blend",
        "seat_standing_method": "provisional_bus_class_split",
        "capacity_confidence": "low",
        "source_record_count": sum(int(item["source_record_count"]) for item in types),
        "source_fleet_count": total_weight,
        "source_trainset_count": math.nan,
        "cars_per_train": math.nan,
        "formation_note": "Joint operator is known, but the actual operator and bus model by departure are unknown.",
    }
    result.update(physical_defaults("bus", 12.0))
    return result


def train_type(
    source: pd.DataFrame,
    *,
    vehicle_type_id: str,
    system_name: str,
    lines: str,
    cars_per_train: int,
    length_m: float,
    formation_note: str,
) -> dict[str, Any]:
    system = source[
        source["mode"].eq("mtr_heavy_rail")
        & source["system_or_service"].eq(system_name)
    ].copy()
    if system.empty:
        raise ValueError(f"Missing heavy-rail source system: {system_name}")
    all_cars = system["fleet_count"].sum()
    trainsets = all_cars / cars_per_train
    passenger = system[system["usable_as_vehicle_capacity"]]
    fleet_capacity = (passenger["model_total_capacity"] * passenger["fleet_count"]).sum()
    fleet_seats = (passenger["model_seats"] * passenger["fleet_count"]).sum()
    model_seats, model_standing, model_total = round_parts(
        fleet_capacity / trainsets, fleet_seats / trainsets
    )
    result = {
        "vehicle_type_id": vehicle_type_id,
        "mode": "mtr",
        "operator": "MTR",
        "system_or_lines": lines,
        "model_seats": model_seats,
        "model_standing": model_standing,
        "model_total_capacity": model_total,
        "capacity_selection_method": "fleet_capacity_divided_by_inferred_trainsets",
        "seat_standing_method": "source_exact_fleet_weighted",
        "capacity_confidence": "medium",
        "source_record_count": int(len(system)),
        "source_fleet_count": float(all_cars),
        "source_trainset_count": float(trainsets),
        "cars_per_train": cars_per_train,
        "formation_note": formation_note,
    }
    result.update(physical_defaults("mtr", length_m))
    return result


def train_variant_type(
    source_rows: pd.DataFrame,
    *,
    vehicle_type_id: str,
    trainsets: int,
    formation_note: str,
) -> dict[str, Any]:
    fleet_capacity = (
        source_rows["model_total_capacity"] * source_rows["fleet_count"]
    ).sum()
    fleet_seats = (source_rows["model_seats"] * source_rows["fleet_count"]).sum()
    model_seats, model_standing, model_total = round_parts(
        fleet_capacity / trainsets, fleet_seats / trainsets
    )
    result = {
        "vehicle_type_id": vehicle_type_id,
        "mode": "mtr",
        "operator": "MTR",
        "system_or_lines": "TML",
        "model_seats": model_seats,
        "model_standing": model_standing,
        "model_total_capacity": model_total,
        "capacity_selection_method": "source_car_counts_exact_variant_formation",
        "seat_standing_method": "source_exact",
        "capacity_confidence": "high",
        "source_record_count": int(len(source_rows)),
        "source_fleet_count": float(source_rows["fleet_count"].sum()),
        "source_trainset_count": float(trainsets),
        "cars_per_train": 8,
        "formation_note": formation_note,
    }
    result.update(physical_defaults("mtr", 192.0))
    return result


def build_vehicle_types(
    source: pd.DataFrame, *, complete_inference: bool = False
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    operator_filters = [
        ("九巴 KMB", "bus_kmb_fleet_weighted", "KMB", "franchised bus", 12.0),
        ("城巴 Citybus", "bus_citybus_fleet_weighted", "Citybus", "franchised bus", 12.0),
        ("新大屿山巴士 NLB", "bus_nlb_fleet_weighted", "NLB", "franchised bus", 11.0),
        ("龙运巴士 LWB", "bus_lwb_fleet_weighted", "LWB", "franchised bus", 12.0),
    ]
    by_id: dict[str, dict[str, Any]] = {}
    for operator_name, type_id, operator, system, length in operator_filters:
        item = weighted_type(
            source[source["operator_name"].eq(operator_name)],
            vehicle_type_id=type_id,
            mode="bus",
            operator=operator,
            system_or_lines=system,
            length_m=length,
            confidence="low",
        )
        records.append(item)
        by_id[type_id] = item

    mtr_bus = weighted_type(
        source[source["mode"].eq("mtr_bus")],
        vehicle_type_id="bus_mtr_fleet_weighted",
        mode="bus",
        operator="MTR",
        system_or_lines="MTR feeder bus",
        length_m=12.0,
        confidence="low",
    )
    records.append(mtr_bus)
    by_id[mtr_bus["vehicle_type_id"]] = mtr_bus

    records.append(
        blended_type(
            [by_id["bus_kmb_fleet_weighted"], by_id["bus_citybus_fleet_weighted"]],
            vehicle_type_id="bus_kmb_citybus_blended",
            operator="KMB+Citybus",
        )
    )
    records.append(
        blended_type(
            [by_id["bus_lwb_fleet_weighted"], by_id["bus_citybus_fleet_weighted"]],
            vehicle_type_id="bus_lwb_citybus_blended",
            operator="LWB+Citybus",
        )
    )

    gmb_source = source[source["mode"].eq("public_light_bus")]
    gmb = weighted_type(
        gmb_source,
        vehicle_type_id="gmb_legal_max_19",
        mode="minibus",
        operator="GMB/RMB",
        system_or_lines="public light bus",
        length_m=7.0,
        confidence="medium",
    )
    gmb["capacity_selection_method"] = "legal_maximum_not_observed_vehicle"
    gmb["formation_note"] = "Nineteen seats is the legal class maximum, not an observed vehicle model assignment."
    records.append(gmb)

    rail_specs = [
        (
            "mtr_urban_8car_fleet_weighted",
            "观塘线、荃湾线、港岛线及将军澳线",
            "KTL/TWL/ISL/TKL",
            8,
            184.0,
            "Pooled 1,016-car fleet divided by the standard 8-car formation; exact fleet by line/departure is unknown.",
        ),
        (
            "mtr_sil_3car_fleet_weighted",
            "南港岛线",
            "SIL",
            3,
            100.0,
            "Thirty source cars divided by the standard 3-car formation.",
        ),
        (
            "mtr_drl_4car_fleet_weighted",
            "迪士尼线",
            "DRL",
            4,
            92.0,
            "Twelve source cars divided by the standard 4-car formation.",
        ),
        (
            "mtr_tcl_8car_fleet_weighted",
            "东涌线",
            "TCL",
            8,
            184.0,
            "All source car variants have total capacity 312; fleet composition by departure is unknown.",
        ),
        (
            "mtr_ael_8car_including_luggage",
            "机场快线",
            "AEL",
            8,
            184.0,
            "Eight-car formation includes one K luggage car with zero passenger capacity.",
        ),
        (
            "mtr_eal_9car_fleet_weighted",
            "东铁线",
            "EAL",
            9,
            216.0,
            "Nine-car formation includes one first-class MFH car; class-specific demand is not modeled.",
        ),
        (
            "mtr_tml_8car_fleet_weighted",
            "屯马线",
            "TML",
            8,
            192.0,
            "Weighted mean of the 48 higher-capacity and 17 lower-capacity 8-car formations inferred from car counts.",
        ),
    ]
    for type_id, system, lines, cars, length, note in rail_specs:
        records.append(
            train_type(
                source,
                vehicle_type_id=type_id,
                system_name=system,
                lines=lines,
                cars_per_train=cars,
                length_m=length,
                formation_note=note,
            )
        )

    lrt_source = source[source["mode"].eq("light_rail")]
    lrt_one = weighted_type(
        lrt_source,
        vehicle_type_id="lrt_fleet_weighted_1car",
        mode="lrt",
        operator="MTR",
        system_or_lines="Light Rail",
        length_m=20.0,
        confidence="low",
    )
    lrt_one["formation_note"] = (
        "One-car type; complete inference assigns one/two-car departures from "
        "three snapshot line-period shares."
        if complete_inference
        else "One-car default; the departure-level one/two-car consist is not available."
    )
    records.append(lrt_one)
    lrt_two = lrt_one.copy()
    lrt_two.update(
        {
            "vehicle_type_id": "lrt_fleet_weighted_2car",
            "model_seats": 2 * int(lrt_one["model_seats"]),
            "model_standing": 2 * int(lrt_one["model_standing"]),
            "model_total_capacity": 2 * int(lrt_one["model_total_capacity"]),
            "cars_per_train": 2,
            "length_m": 40.0,
            "formation_note": (
                "Two-car type assigned from three snapshot line-period shares."
                if complete_inference
                else "Two-car alternative; departure-level consist assignment is not available."
            ),
        }
    )
    records.append(lrt_two)

    tram_source = source[
        source["mode"].eq("tram")
        & source["usable_as_vehicle_capacity"]
        & source["source_capacity_min"].eq(115)
    ]
    tram = weighted_type(
        tram_source,
        vehicle_type_id="tram_standard_115",
        mode="tram",
        operator="Hong Kong Tramways",
        system_or_lines="Hong Kong Island tram",
        length_m=10.7,
        confidence="low",
    )
    tram["capacity_selection_method"] = "standard_service_source_total"
    tram["formation_note"] = "Standard 115-person tram only; heritage/special and maintenance cars are excluded."
    records.append(tram)

    hsr_source = source[source["mode"].eq("high_speed_rail")]
    hsr_total = hsr_source["model_total_capacity"].sum()
    hsr_seats = hsr_source["model_seats"].sum()
    hsr_model_seats, hsr_standing, hsr_model_total = round_parts(hsr_total, hsr_seats)
    hsr = {
        "vehicle_type_id": "hsr_vibrant_express_8car",
        "mode": "hsr",
        "operator": "MTR",
        "system_or_lines": "Guangzhou-Shenzhen-Hong Kong Express Rail Link",
        "model_seats": hsr_model_seats,
        "model_standing": hsr_standing,
        "model_total_capacity": hsr_model_total,
        "capacity_selection_method": "sum_of_eight_numbered_car_capacities",
        "seat_standing_method": "reserved_capacity_as_seats",
        "capacity_confidence": "high",
        "source_record_count": int(len(hsr_source)),
        "source_fleet_count": float(hsr_source["fleet_count"].sum()),
        "source_trainset_count": 9.0,
        "cars_per_train": 8,
        "formation_note": "Each numbered car appears nine times, supporting nine identical 8-car trainsets.",
    }
    hsr.update(physical_defaults("hsr", 200.0))
    records.append(hsr)

    if complete_inference:
        tml = source[
            source["mode"].eq("mtr_heavy_rail")
            & source["system_or_service"].eq("屯马线")
        ].copy()
        high = tml[
            tml["vehicle_or_car_type"].str.contains(
                r"321 configuration|335 configuration|H car", regex=True, na=False
            )
        ]
        low = tml[
            tml["vehicle_or_car_type"].str.contains(
                r"308 configuration|328 configuration|329 configuration|K car",
                regex=True,
                na=False,
            )
        ]
        if high["fleet_count"].sum() != 384 or low["fleet_count"].sum() != 136:
            raise ValueError("Unexpected TML car counts for 48/17 trainset inference")
        records.append(
            train_variant_type(
                high,
                vehicle_type_id="mtr_tml_8car_high_capacity",
                trainsets=48,
                formation_note=(
                    "48 inferred 8-car formations: 2D(321)+2P(335)+"
                    "2M(335)+C(335)+H(335)."
                ),
            )
        )
        records.append(
            train_variant_type(
                low,
                vehicle_type_id="mtr_tml_8car_low_capacity",
                trainsets=17,
                formation_note=(
                    "17 inferred 8-car formations: 2D(308)+2P(328)+"
                    "2M(329)+C(328)+K(328)."
                ),
            )
        )

        bus_source = source[source["mode"].isin(["franchised_bus", "mtr_bus"])]
        single = bus_source[
            bus_source["vehicle_class"].str.contains("单层", na=False)
        ]
        xb = weighted_type(
            single,
            vehicle_type_id="bus_xb_single_deck_coach_proxy",
            mode="bus",
            operator="XB proxy",
            system_or_lines="cross-boundary coach",
            length_m=12.0,
            confidence="very_low",
        )
        xb["model_seats"] = xb["model_total_capacity"]
        xb["model_standing"] = 0
        xb["capacity_selection_method"] = (
            "all_available_single_deck_fleet_weighted_capacity_proxy"
        )
        xb["seat_standing_method"] = "coach_proxy_all_capacity_as_seats"
        xb["formation_note"] = (
            "No cross-boundary coach capacity source; inferred from the 291 "
            "single-deck buses in the supplied catalog and treated as seated-only."
        )
        records.append(xb)

        db = by_id["bus_nlb_fleet_weighted"].copy()
        db.update(
            {
                "vehicle_type_id": "bus_db_nlb_island_service_proxy",
                "operator": "DB proxy",
                "system_or_lines": "Discovery Bay bus",
                "capacity_selection_method": "nlb_island_service_fleet_proxy",
                "capacity_confidence": "very_low",
                "formation_note": (
                    "No Discovery Bay fleet source; NLB is used as the closest "
                    "island/exurban bus fleet in the supplied catalog."
                ),
            }
        )
        records.append(db)

        pi = weighted_type(
            single,
            vehicle_type_id="bus_pi_single_deck_shuttle_proxy",
            mode="bus",
            operator="PI proxy",
            system_or_lines="Park Island shuttle bus",
            length_m=12.0,
            confidence="very_low",
        )
        pi["capacity_selection_method"] = (
            "all_available_single_deck_fleet_weighted_capacity_proxy"
        )
        pi["formation_note"] = (
            "No Park Island fleet source; inferred from all single-deck buses "
            "in the supplied catalog."
        )
        records.append(pi)

        fallback = weighted_type(
            bus_source,
            vehicle_type_id="bus_hk_all_fleet_fallback",
            mode="bus",
            operator="unspecified proxy",
            system_or_lines="stale or unspecified bus routes",
            length_m=12.0,
            confidence="very_low",
        )
        fallback["capacity_selection_method"] = "all_available_bus_fleet_weighted_proxy"
        fallback["formation_note"] = (
            "Used only for five stale/manual-review routes whose operator is absent."
        )
        records.append(fallback)

    result = pd.DataFrame(records)[TYPE_COLUMNS]
    if result["vehicle_type_id"].duplicated().any():
        raise ValueError("Duplicate MATSim vehicle type IDs")
    mismatch = result["model_seats"] + result["model_standing"] - result["model_total_capacity"]
    if mismatch.abs().max() != 0:
        raise ValueError("Vehicle type seats + standing does not equal total")
    return result


def assignment_for_route(
    row: pd.Series, *, complete_inference: bool = False
) -> tuple[str | None, str, str]:
    mode = str(row.get("mode", ""))
    if mode == "mtr":
        type_id = MTR_LINE_TO_TYPE.get(str(row.get("route_id", "")))
        return (
            type_id,
            "derived_line_train_formation" if type_id else "missing_line_mapping",
            "medium" if type_id else "none",
        )
    if mode == "lrt":
        return (
            "lrt_fleet_weighted_1car",
            (
                "route_default_departures_use_snapshot_consist_mix"
                if complete_inference
                else "provisional_one_car_default"
            ),
            "medium" if complete_inference else "low",
        )
    if mode == "gmb":
        return "gmb_legal_max_19", "legal_class_maximum", "medium"
    if mode == "bus":
        company = str(row.get("company_code", ""))
        type_id = BUS_COMPANY_TO_TYPE.get(company)
        if complete_inference and not type_id:
            proxy_types = {
                "XB": "bus_xb_single_deck_coach_proxy",
                "DB": "bus_db_nlb_island_service_proxy",
                "PI": "bus_pi_single_deck_shuttle_proxy",
                "nan": "bus_hk_all_fleet_fallback",
                "": "bus_hk_all_fleet_fallback",
                "None": "bus_hk_all_fleet_fallback",
            }
            type_id = proxy_types.get(company, "bus_hk_all_fleet_fallback")
            return type_id, "complete_inference_service_proxy", "very_low"
        return (
            type_id,
            "operator_fleet_representative" if type_id else "missing_operator_capacity_source",
            "low" if type_id else "none",
        )
    return None, "unsupported_mode", "none"


def build_route_assignments(
    route_qa_path: Path,
    type_ids: set[str],
    *,
    complete_inference: bool = False,
) -> pd.DataFrame:
    route_qa = pd.read_csv(route_qa_path)
    required = {"route_key", "mode", "route_id", "company_code", "acceptance_status"}
    missing = sorted(required - set(route_qa.columns))
    if missing:
        raise ValueError(f"Route QA is missing columns: {missing}")
    rows = []
    for _, route in route_qa.iterrows():
        type_id, method, confidence = assignment_for_route(
            route, complete_inference=complete_inference
        )
        if type_id and type_id not in type_ids:
            raise ValueError(f"Route mapped to unknown vehicle type {type_id}")
        rows.append(
            {
                "route_key": route["route_key"],
                "mode": route["mode"],
                "route_id": route["route_id"],
                "route_seq": route.get("route_seq"),
                "company_code": route.get("company_code"),
                "route_name": route.get("route_name"),
                "map_matching_acceptance_status": route["acceptance_status"],
                "vehicle_type_id": type_id,
                "assignment_method": method,
                "assignment_confidence": confidence,
                "capacity_assignment_status": "assigned" if type_id else "missing",
            }
        )
    return pd.DataFrame(rows)


def snapshot_period(captured_at_utc: str) -> str:
    timestamp = pd.Timestamp(captured_at_utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    local = timestamp.tz_convert("Asia/Hong_Kong")
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    if 7 * 3600 <= seconds < 9 * 3600 + 30 * 60:
        return "weekday_morning_peak"
    if 17 * 3600 <= seconds < 20 * 3600:
        return "weekday_evening_peak"
    return "weekday_non_peak"


def build_lrt_snapshot_evidence(
    snapshot_dirs: list[Path], lrt_lines: list[str]
) -> pd.DataFrame:
    observations: list[dict[str, Any]] = []
    for snapshot_dir in snapshot_dirs:
        path = snapshot_dir / "light_rail_next_train.jsonl"
        if not path.exists():
            raise FileNotFoundError(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            captured = str(record.get("captured_at_utc", ""))
            period = snapshot_period(captured)
            response = record.get("response") or {}
            for platform in response.get("platform_list") or []:
                for train in platform.get("route_list") or []:
                    train_length = pd.to_numeric(train.get("train_length"), errors="coerce")
                    route_no = str(train.get("route_no", "")).strip()
                    if train_length not in (1, 2) or not route_no:
                        continue
                    observations.append(
                        {
                            "snapshot_dir": snapshot_dir.name,
                            "captured_at_utc": captured,
                            "observed_period_code": period,
                            "line_code": route_no,
                            "train_length": int(train_length),
                        }
                    )
    raw = pd.DataFrame(observations)
    if raw.empty:
        raise ValueError("No one/two-car Light Rail observations in snapshots")

    periods = [
        "weekday_morning_peak",
        "weekday_evening_peak",
        "weekday_non_peak",
    ]
    records: list[dict[str, Any]] = []
    for line_code in sorted(set(map(str, lrt_lines))):
        line_all = raw[raw["line_code"].eq(line_code)]
        for period in periods:
            direct = line_all[line_all["observed_period_code"].eq(period)]
            if not direct.empty:
                evidence = direct
                method = "direct_line_period_snapshot_observations"
            elif not line_all.empty:
                evidence = line_all
                method = "line_all_snapshots_fallback_no_period_snapshot"
            else:
                evidence = raw
                method = "all_lrt_snapshots_fallback_no_line_observation"
            two_count = int(evidence["train_length"].eq(2).sum())
            observation_count = int(len(evidence))
            records.append(
                {
                    "line_code": line_code,
                    "period_code": period,
                    "observation_count": observation_count,
                    "one_car_observations": observation_count - two_count,
                    "two_car_observations": two_count,
                    "target_two_car_share": two_count / observation_count,
                    "evidence_method": method,
                    "snapshot_count": int(evidence["snapshot_dir"].nunique()),
                    "snapshot_dirs": ";".join(sorted(evidence["snapshot_dir"].unique())),
                    "weighting_note": (
                        "Station-prediction weighted; the same physical train may "
                        "appear at multiple stations."
                    ),
                }
            )
    return pd.DataFrame(records)


def systematic_binary_allocation(size: int, selected: int) -> list[bool]:
    if not 0 <= selected <= size:
        raise ValueError("Invalid systematic allocation target")
    result: list[bool] = []
    accumulator = 0
    for _ in range(size):
        accumulator += selected
        if accumulator >= size:
            result.append(True)
            accumulator -= size
        else:
            result.append(False)
    if sum(result) != selected:
        raise RuntimeError("Systematic allocation did not conserve selected count")
    return result


def build_timetable_assignments(
    timetable_dir: Path,
    type_ids: set[str],
    *,
    complete_inference: bool = False,
    snapshot_dirs: list[Path] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    patterns = pd.read_csv(timetable_dir / "approximate_route_patterns.csv")
    departures = pd.read_csv(timetable_dir / "approximate_origin_departures.csv")
    pattern_rows = []
    for _, pattern in patterns.iterrows():
        if pattern["mode"] == "mtr":
            type_id = MTR_LINE_TO_TYPE.get(str(pattern["line_code"]))
            method = "derived_line_train_formation"
            confidence = "medium"
        else:
            type_id = "lrt_fleet_weighted_1car"
            method = (
                "pattern_default_departures_use_snapshot_consist_mix"
                if complete_inference
                else "provisional_one_car_default"
            )
            confidence = "low"
        if type_id not in type_ids:
            raise ValueError(f"Timetable pattern mapped to unknown type {type_id}")
        pattern_rows.append(
            {
                "route_variant_id": pattern["route_variant_id"],
                "mode": pattern["mode"],
                "line_code": pattern["line_code"],
                "direction": pattern["direction"],
                "vehicle_type_id": type_id,
                "assignment_method": method,
                "assignment_confidence": confidence,
                "actual_consist_known": False,
                "departure_assignment_varies": bool(
                    complete_inference
                    and (pattern["mode"] == "lrt" or pattern["line_code"] == "TML")
                ),
            }
        )
    pattern_assignments = pd.DataFrame(pattern_rows)
    departure_assignments = departures.merge(
        pattern_assignments[
            [
                "route_variant_id",
                "vehicle_type_id",
                "assignment_method",
                "assignment_confidence",
                "actual_consist_known",
            ]
        ],
        on="route_variant_id",
        how="left",
        validate="many_to_one",
    )
    if departure_assignments["vehicle_type_id"].isna().any():
        raise ValueError("Some timetable departures have no vehicle type")

    fixed_cars = {
        "AEL": 8,
        "DRL": 4,
        "EAL": 9,
        "ISL": 8,
        "KTL": 8,
        "SIL": 3,
        "TCL": 8,
        "TKL": 8,
        "TML": 8,
        "TWL": 8,
    }
    departure_assignments["consist_cars"] = departure_assignments["line_code"].map(
        fixed_cars
    )
    departure_assignments.loc[
        departure_assignments["mode"].eq("lrt"), "consist_cars"
    ] = 1
    departure_assignments["capacity_inference_detail"] = (
        "line_level_fleet_weighted_formation"
    )

    lrt_evidence = pd.DataFrame()
    if complete_inference:
        tml_index = departure_assignments.index[
            departure_assignments["line_code"].eq("TML")
        ].tolist()
        ordered_tml = departure_assignments.loc[tml_index].sort_values(
            ["departure_seconds", "route_variant_id", "departure_sequence"]
        )
        high_target = int(round(len(ordered_tml) * 48 / 65))
        high_flags = systematic_binary_allocation(len(ordered_tml), high_target)
        for index, high_flag in zip(ordered_tml.index, high_flags):
            departure_assignments.at[index, "vehicle_type_id"] = (
                "mtr_tml_8car_high_capacity"
                if high_flag
                else "mtr_tml_8car_low_capacity"
            )
            departure_assignments.at[index, "assignment_method"] = (
                "tml_48_to_17_fleet_mix_systematic"
            )
            departure_assignments.at[index, "assignment_confidence"] = "medium"
            departure_assignments.at[index, "capacity_inference_detail"] = (
                "high_capacity_48_trainset_share"
                if high_flag
                else "low_capacity_17_trainset_share"
            )

        lrt_lines = sorted(
            departure_assignments.loc[
                departure_assignments["mode"].eq("lrt"), "line_code"
            ]
            .astype(str)
            .unique()
        )
        lrt_evidence = build_lrt_snapshot_evidence(
            snapshot_dirs or [], lrt_lines
        )
        lrt_mask = departure_assignments["mode"].eq("lrt")
        for (line_code, period_code), group in departure_assignments[lrt_mask].groupby(
            ["line_code", "period_code"], sort=True
        ):
            evidence = lrt_evidence[
                lrt_evidence["line_code"].eq(str(line_code))
                & lrt_evidence["period_code"].eq(period_code)
            ]
            if len(evidence) != 1:
                raise ValueError(f"Missing LRT evidence for {line_code}/{period_code}")
            target_share = float(evidence.iloc[0]["target_two_car_share"])
            ordered = group.sort_values(
                ["departure_seconds", "route_variant_id", "departure_sequence"]
            )
            two_target = int(round(len(ordered) * target_share))
            two_flags = systematic_binary_allocation(len(ordered), two_target)
            for index, two_flag in zip(ordered.index, two_flags):
                departure_assignments.at[index, "vehicle_type_id"] = (
                    "lrt_fleet_weighted_2car"
                    if two_flag
                    else "lrt_fleet_weighted_1car"
                )
                departure_assignments.at[index, "consist_cars"] = 2 if two_flag else 1
                departure_assignments.at[index, "assignment_method"] = (
                    "lrt_snapshot_line_period_share_systematic"
                )
                departure_assignments.at[index, "assignment_confidence"] = "medium"
                departure_assignments.at[index, "capacity_inference_detail"] = (
                    f"target_two_car_share={target_share:.6f};"
                    f"evidence={evidence.iloc[0]['evidence_method']}"
                )

        if not set(departure_assignments["vehicle_type_id"]) <= type_ids:
            raise ValueError("Complete inference assigned an unknown vehicle type")
    departure_assignments.insert(
        1,
        "vehicle_id",
        "hkpt_" + departure_assignments["departure_id"].astype(str),
    )
    departure_assignments["vehicle_instance_method"] = (
        "one_vehicle_per_departure_no_block_reuse"
    )
    return pattern_assignments, departure_assignments, lrt_evidence


def vehicle_definitions_xml(
    path: Path,
    types: pd.DataFrame,
    vehicles: pd.DataFrame | None = None,
) -> None:
    root = ET.Element("vehicleDefinitions")
    for _, item in types.iterrows():
        vehicle_type = ET.SubElement(
            root, "vehicleType", {"id": str(item["vehicle_type_id"])}
        )
        ET.SubElement(
            vehicle_type,
            "capacity",
            {
                "seats": str(int(item["model_seats"])),
                "standingRoomInPersons": str(int(item["model_standing"])),
            },
        )
        ET.SubElement(vehicle_type, "length", {"meter": str(float(item["length_m"]))})
        ET.SubElement(vehicle_type, "width", {"meter": str(float(item["width_m"]))})
        ET.SubElement(
            vehicle_type,
            "accessTime",
            {"secondsPerPerson": str(float(item["access_time_s_per_person"]))},
        )
        ET.SubElement(
            vehicle_type,
            "egressTime",
            {"secondsPerPerson": str(float(item["egress_time_s_per_person"]))},
        )
        ET.SubElement(
            vehicle_type, "doorOperation", {"mode": str(item["door_operation"])}
        )
        ET.SubElement(
            vehicle_type, "passengerCarEquivalents", {"pce": str(float(item["pce"]))}
        )
    if vehicles is not None:
        for _, vehicle in vehicles.iterrows():
            ET.SubElement(
                root,
                "vehicle",
                {
                    "id": str(vehicle["vehicle_id"]),
                    "type": str(vehicle["vehicle_type_id"]),
                },
            )
    ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    xml_text = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE vehicleDefinitions SYSTEM "http://www.matsim.org/files/dtd/vehicleDefinitions_v1.dtd">\n\n'
        + xml_body
        + "\n"
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)


def validate_xml(path: Path) -> tuple[int, int]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        root = ET.parse(handle).getroot()
    return len(root.findall("vehicleType")), len(root.findall("vehicle"))


def gap_inventory(
    source: pd.DataFrame,
    route_assignments: pd.DataFrame,
    *,
    complete_inference: bool = False,
) -> pd.DataFrame:
    missing_routes = route_assignments[route_assignments["capacity_assignment_status"].eq("missing")]
    missing_company_counts = (
        missing_routes["company_code"].fillna("UNSPECIFIED").value_counts().to_dict()
    )
    total_only = int(
        (source["usable_as_vehicle_capacity"] & source["source_seats"].isna()).sum()
    )
    proxy_routes = route_assignments[
        route_assignments["assignment_method"].eq("complete_inference_service_proxy")
    ]
    gaps = [
        (
            "critical",
            "route_specific_vehicle_allocation",
            "Bus/GMB route and departure records do not identify the operated vehicle model.",
            "With no further data, retain operator fleet-weighted expected capacities and test lower/upper capacity sensitivity rather than treating the assigned model as observed.",
        ),
        (
            "critical",
            "rail_departure_consist",
            (
                "TML variants are allocated in the 48:17 fleet ratio and Light Rail "
                "one/two-car consists use three snapshot line-period shares, but neither "
                "is an observed full-day consist roster."
                if complete_inference
                else "MTR departures lack fleet variant and Light Rail departures lack one-car/two-car consist assignments."
            ),
            "Treat the inferred mix as the base case and retain one-car/two-car and low/high train sensitivity cases.",
        ),
        (
            "critical",
            "vehicle_blocks_and_reuse",
            "There are no vehicle blocks, depot pull-outs, turnarounds, or interlining links.",
            "Build vehicle blocks before fleet-count, layover, or depot simulation. The XML currently creates one vehicle per rail departure.",
        ),
        (
            "high" if not complete_inference else "medium",
            "uncovered_or_proxy_route_operators",
            (
                f"{len(proxy_routes)} directions use low-confidence service proxies; "
                f"{len(missing_routes)} remain missing."
                if complete_inference
                else f"{len(missing_routes)} mapped directions have no capacity source: {missing_company_counts}."
            ),
            "Use the complete proxy allocation as the base case and report XB/DB/PI proxy sensitivity separately.",
        ),
        (
            "high",
            "seat_standing_split",
            f"{total_only} usable source rows provide total capacity but no seats/standing split.",
            "Replace provisional bus, Light Rail, tram, and ferry split ratios with model-level licensed seating plans.",
        ),
        (
            "high",
            "ferry_route_vessel_assignment",
            "Ferry rows lack complete vessel counts and route-to-vessel schedules; the Star Ferry value is a whole-fleet total, not vessel capacity.",
            "Collect per-vessel capacities, vessel IDs, sailing assignments, and timetables before creating ferry vehicle types for service.",
        ),
        (
            "medium",
            "mtr_train_formation_source",
            "Cars-per-train formations are model assumptions used to convert car capacity to train capacity.",
            "Confirm line and fleet-specific formations, especially pooled urban lines and the two Tuen Ma Line capacity variants.",
        ),
        (
            "medium",
            "physical_and_door_parameters",
            "Vehicle length, width, access/egress time, door operation, and PCE are provisional mode defaults rather than values from the capacity table.",
            "Replace defaults using manufacturer specifications and observed boarding/alighting data.",
        ),
        (
            "medium",
            "wheelchair_and_accessibility",
            f"Wheelchair-place values are missing in {int(source['wheelchair_places'].isna().sum())} of 169 source records and are not represented by the MATSim v1 capacity element.",
            "Complete accessibility fields and decide whether to model them through vehicle attributes or a custom constraint.",
        ),
        (
            "medium",
            "data_vintage",
            "Most fleet records are dated 2024-12-31 even though the digest is the 2025 edition.",
            "Refresh fleet counts and new/retired models to the intended MATSim scenario year (2026).",
        ),
        (
            "medium",
            "non_current_supply_modes",
            "Tram, ferry, and high-speed-rail capacities are catalogued but their routes, departures, stop offsets, and vehicle assignments are not yet in the current schedule workflow.",
            "Complete those mode-specific schedules and map-matched route sequences before enabling their vehicle types.",
        ),
        (
            "low",
            "capacity_range_choice",
            "Where the source provides a capacity range, the representative catalog uses its midpoint.",
            "Use exact registration/model variants or run lower/mid/upper capacity sensitivity tests.",
        ),
    ]
    return pd.DataFrame(
        gaps, columns=["severity", "gap_id", "current_limitation", "required_action"]
    )


def main() -> None:
    args = parse_args()
    transit_root = args.data_root / "transit/hongkong"
    route_qa = args.route_qa or (
        transit_root
        / "processed/transit_route_link_mapmatching_2026_v2/route_map_matching_qa.csv"
    )
    timetable_dir = args.timetable_dir or (
        transit_root / "processed/mtr_lrt_approximate_timetable_2026_weekday"
    )
    output_dir = args.output_dir or (
        transit_root
        / (
            "processed/public_transport_vehicle_capacities_inferred_2026"
            if args.complete_inference
            else "processed/public_transport_vehicle_capacities_2025"
        )
    )
    snapshot_dirs = args.snapshot_dir or [
        transit_root / "API_Supplements/realtime_snapshots" / name
        for name in DEFAULT_SNAPSHOT_NAMES
    ]
    required_paths = [
        args.capacity_csv,
        route_qa,
        timetable_dir / "approximate_route_patterns.csv",
        timetable_dir / "approximate_origin_departures.csv",
    ]
    if args.complete_inference:
        required_paths.extend(
            snapshot_dir / "light_rail_next_train.jsonl"
            for snapshot_dir in snapshot_dirs
        )
    for required in required_paths:
        if not required.exists():
            raise FileNotFoundError(required)

    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "source"
    source_dir.mkdir(exist_ok=True)
    copied_source = source_dir / args.capacity_csv.name
    shutil.copy2(args.capacity_csv, copied_source)

    source = normalized_source(args.capacity_csv)
    vehicle_types = build_vehicle_types(
        source, complete_inference=args.complete_inference
    )
    type_ids = set(vehicle_types["vehicle_type_id"])
    route_assignments = build_route_assignments(
        route_qa, type_ids, complete_inference=args.complete_inference
    )
    pattern_assignments, departure_assignments, lrt_evidence = build_timetable_assignments(
        timetable_dir,
        type_ids,
        complete_inference=args.complete_inference,
        snapshot_dirs=snapshot_dirs,
    )
    gaps = gap_inventory(
        source,
        route_assignments,
        complete_inference=args.complete_inference,
    )

    source.to_csv(output_dir / "normalized_vehicle_capacity_records.csv", index=False, encoding="utf-8-sig")
    vehicle_types.to_csv(output_dir / "matsim_vehicle_types.csv", index=False, encoding="utf-8-sig")
    route_assignments.to_csv(output_dir / "route_vehicle_type_assignments.csv", index=False, encoding="utf-8-sig")
    pattern_assignments.to_csv(output_dir / "mtr_lrt_pattern_vehicle_type_assignments.csv", index=False, encoding="utf-8-sig")
    departure_assignments.to_csv(output_dir / "mtr_lrt_departure_vehicle_assignments.csv", index=False, encoding="utf-8-sig")
    gaps.to_csv(output_dir / "remaining_vehicle_data_gaps.csv", index=False, encoding="utf-8-sig")
    if not lrt_evidence.empty:
        lrt_evidence.to_csv(
            output_dir / "lrt_snapshot_consist_evidence.csv",
            index=False,
            encoding="utf-8-sig",
        )
    route_allocation_summary = (
        route_assignments.groupby(
            [
                "mode",
                "company_code",
                "vehicle_type_id",
                "assignment_method",
                "assignment_confidence",
            ],
            dropna=False,
        )
        .size()
        .rename("route_direction_count")
        .reset_index()
    )
    route_allocation_summary.to_csv(
        output_dir / "route_capacity_allocation_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    departure_allocation_summary = (
        departure_assignments.groupby(
            ["mode", "line_code", "period_code", "vehicle_type_id", "consist_cars"],
            dropna=False,
        )
        .size()
        .rename("departure_count")
        .reset_index()
    )
    departure_allocation_summary.to_csv(
        output_dir / "departure_capacity_allocation_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    type_xml = output_dir / "transitVehicleTypes.xml.gz"
    rail_xml = output_dir / "mtr_lrt_transitVehicles_approximate.xml.gz"
    vehicle_definitions_xml(type_xml, vehicle_types)
    vehicle_definitions_xml(rail_xml, vehicle_types, departure_assignments)
    type_xml_counts = validate_xml(type_xml)
    rail_xml_counts = validate_xml(rail_xml)

    source_mode_counts = source["mode"].value_counts().sort_index().to_dict()
    assignment_counts = (
        route_assignments.groupby(["mode", "capacity_assignment_status"])
        .size()
        .rename("count")
        .reset_index()
        .to_dict(orient="records")
    )
    missing_by_company = (
        route_assignments.loc[
            route_assignments["capacity_assignment_status"].eq("missing"),
            "company_code",
        ]
        .fillna("UNSPECIFIED")
        .value_counts()
        .to_dict()
    )
    qa_rows = [
        ("source_record_count", len(source), 169, len(source) == 169),
        ("usable_per_vehicle_source_records", int(source["usable_as_vehicle_capacity"].sum()), 166, int(source["usable_as_vehicle_capacity"].sum()) == 166),
        ("excluded_source_records", int((~source["usable_as_vehicle_capacity"]).sum()), 3, int((~source["usable_as_vehicle_capacity"]).sum()) == 3),
        ("vehicle_type_count", len(vehicle_types), len(vehicle_types), True),
        ("route_assignment_row_count", len(route_assignments), 3570, len(route_assignments) == 3570),
        ("route_capacity_assigned_count", int(route_assignments["vehicle_type_id"].notna().sum()), 3570 if args.complete_inference else 3507, int(route_assignments["vehicle_type_id"].notna().sum()) == (3570 if args.complete_inference else 3507)),
        ("timetable_pattern_count", len(pattern_assignments), 50, len(pattern_assignments) == 50),
        ("timetable_departure_count", len(departure_assignments), 7461, len(departure_assignments) == 7461),
        ("type_xml_vehicle_types", type_xml_counts[0], len(vehicle_types), type_xml_counts[0] == len(vehicle_types)),
        ("type_xml_vehicle_instances", type_xml_counts[1], 0, type_xml_counts[1] == 0),
        ("rail_xml_vehicle_types", rail_xml_counts[0], len(vehicle_types), rail_xml_counts[0] == len(vehicle_types)),
        ("rail_xml_vehicle_instances", rail_xml_counts[1], len(departure_assignments), rail_xml_counts[1] == len(departure_assignments)),
        ("capacity_sum_conservation", int(((vehicle_types['model_seats'] + vehicle_types['model_standing']) == vehicle_types['model_total_capacity']).sum()), len(vehicle_types), bool(((vehicle_types['model_seats'] + vehicle_types['model_standing']) == vehicle_types['model_total_capacity']).all())),
    ]
    if args.complete_inference:
        lrt_departures = departure_assignments[departure_assignments["mode"].eq("lrt")]
        tml_departures = departure_assignments[
            departure_assignments["line_code"].eq("TML")
        ]
        qa_rows.extend(
            [
                ("complete_vehicle_type_count", len(vehicle_types), 25, len(vehicle_types) == 25),
                ("lrt_consist_evidence_rows", len(lrt_evidence), 33, len(lrt_evidence) == 33),
                ("lrt_departures_with_one_or_two_cars", int(lrt_departures["consist_cars"].isin([1, 2]).sum()), len(lrt_departures), bool(lrt_departures["consist_cars"].isin([1, 2]).all())),
                ("tml_departures_variant_assigned", int(tml_departures["vehicle_type_id"].isin(["mtr_tml_8car_high_capacity", "mtr_tml_8car_low_capacity"]).sum()), len(tml_departures), bool(tml_departures["vehicle_type_id"].isin(["mtr_tml_8car_high_capacity", "mtr_tml_8car_low_capacity"]).all())),
            ]
        )
    qa = pd.DataFrame(qa_rows, columns=["check", "actual", "expected", "passed"])
    qa.to_csv(output_dir / "vehicle_capacity_qa.csv", index=False, encoding="utf-8-sig")
    if not qa["passed"].all():
        raise RuntimeError(f"Vehicle-capacity QA failed:\n{qa.loc[~qa['passed']].to_string(index=False)}")

    summary = {
        "complete_inference": args.complete_inference,
        "source": {
            "input_path": str(args.capacity_csv.resolve()),
            "copied_path": str(copied_source.resolve()),
            "sha256": sha256_file(copied_source),
            "records": len(source),
            "mode_counts": source_mode_counts,
            "statistics_dates": sorted(source["statistics_date"].dropna().astype(str).unique()),
            "usable_per_vehicle_records": int(source["usable_as_vehicle_capacity"].sum()),
            "excluded_records": int((~source["usable_as_vehicle_capacity"]).sum()),
            "records_with_exact_seat_standing": int(source["seat_standing_method"].eq("source_exact").sum()),
            "records_with_provisional_seat_standing": int((source["usable_as_vehicle_capacity"] & source["seat_standing_method"].ne("source_exact")).sum()),
        },
        "matsim_types": {
            "count": len(vehicle_types),
            "ids": vehicle_types["vehicle_type_id"].tolist(),
            "capacity_definition": "seats + standingRoomInPersons",
            "range_rule": "midpoint",
            "physical_parameters": "provisional mode defaults",
        },
        "route_assignments": {
            "rows": len(route_assignments),
            "assigned": int(route_assignments["capacity_assignment_status"].eq("assigned").sum()),
            "missing": int(route_assignments["capacity_assignment_status"].eq("missing").sum()),
            "counts": assignment_counts,
            "missing_by_company": missing_by_company,
            "proxy_assignment_count": int(
                route_assignments["assignment_method"]
                .eq("complete_inference_service_proxy")
                .sum()
            ),
        },
        "mtr_lrt_timetable": {
            "patterns": len(pattern_assignments),
            "departures": len(departure_assignments),
            "all_assigned": bool(departure_assignments["vehicle_type_id"].notna().all()),
            "vehicle_instance_strategy": "one_vehicle_per_departure_no_block_reuse",
            "light_rail_assignment": (
                "three_snapshot_line_period_one_two_car_mix"
                if args.complete_inference
                else "one_car_default"
            ),
            "light_rail_consist_counts": (
                departure_assignments.loc[
                    departure_assignments["mode"].eq("lrt"), "consist_cars"
                ]
                .value_counts()
                .sort_index()
                .to_dict()
            ),
            "tml_vehicle_type_counts": (
                departure_assignments.loc[
                    departure_assignments["line_code"].eq("TML"),
                    "vehicle_type_id",
                ]
                .value_counts()
                .to_dict()
            ),
            "snapshot_dirs": [str(path.resolve()) for path in snapshot_dirs]
            if args.complete_inference
            else [],
        },
        "xml": {
            "type_library": str(type_xml.resolve()),
            "rail_departure_vehicles": str(rail_xml.resolve()),
            "vehicle_definition_dtd": "vehicleDefinitions_v1.dtd",
        },
        "important_limitations": gaps.to_dict(orient="records"),
    }
    write_json(output_dir / "vehicle_capacity_integration_summary.json", summary)

    files = sorted(
        path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    checksum_lines = [
        f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}" for path in files
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="ascii"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
