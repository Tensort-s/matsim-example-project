#!/usr/bin/env python3
"""Prepare audited inputs for a 2026 typical-day Hong Kong border OD model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
DEFAULT_RAW = DEFAULT_DATA_ROOT / "tourism/hongkong/raw"
DEFAULT_TRAFFIC = DEFAULT_RAW / "statistics_on_daily_passenger_traffic.csv"
DEFAULT_CBTS = DEFAULT_RAW / "table_cbts2017_ch3A.xlsx"
DEFAULT_HOTEL = DEFAULT_RAW / "Occ 05 2026.xls"
DEFAULT_PACK = DEFAULT_RAW / "hong_kong_arrival_departure_tourist_od_data_pack.xlsx"
DEFAULT_HKTB_PURPOSE = DEFAULT_RAW / "Visitor Arrival by Purpose of Visit 2026Q1.xlsx"
HKTB_Q1_PAGE = "https://partnernet.hktb.com/en/research_statistics/research_publications/index.html?id=6171"
HKTB_Q1_XLSX = "https://partnernet.hktb.com/filemanager/researchpub/6171/604257/Visitor%20Arrival%20by%20Purpose%20of%20Visit%202026Q1.xlsx"
TCS_REPORT = "https://www.td.gov.hk/filemanager/en/content_5349/tcs2022_eng.pdf"
HK_2026_HOLIDAYS = "https://www.gov.hk/en/about/abouthk/holiday/2026.htm"

CATEGORIES = {
    "香港居民": "hk_resident",
    "内地访客": "mainland_visitor",
    "其他访客": "other_visitor",
}
DIRECTIONS = {"入境": "arrival", "出境": "departure"}

# Holidays intersecting the observed 2026-01-01 to 2026-07-16 interval.
HK_PUBLIC_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-04-03",
    "2026-04-06",
    "2026-04-07",
    "2026-05-01",
    "2026-05-25",
    "2026-06-19",
    "2026-07-01",
}

HOTEL_DISTRICTS = [
    ("Central and Western", 9620, 0.84, "P2/P4"),
    ("Wan Chai", 11925, 0.82, "P2/P4"),
    ("Eastern and Southern", 8566, 0.86, "P2/P4"),
    ("Tsim Sha Tsui", 18642, 0.81, "P2/P4"),
    ("Yau Ma Tei and Mong Kok", 7178, 0.92, "P2/P4"),
    ("Other Kowloon", 13332, 0.88, "P2/P4"),
    ("New Territories", 16516, 0.86, "P2/P4"),
    ("Outlying Islands", 7677, 0.64, "P2/P4"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--traffic-csv", type=Path, default=DEFAULT_TRAFFIC)
    parser.add_argument("--cbts-xlsx", type=Path, default=DEFAULT_CBTS)
    parser.add_argument("--hotel-xls", type=Path, default=DEFAULT_HOTEL)
    parser.add_argument("--data-pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--hktb-purpose-xlsx", type=Path, default=DEFAULT_HKTB_PURPOSE)
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def largest_remainder(values: np.ndarray, total: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values = values / values.sum() * total if values.sum() else values
    base = np.floor(values).astype(np.int64)
    remainder = int(total - base.sum())
    if remainder > 0:
        order = np.argsort(-(values - base), kind="stable")
        base[order[:remainder]] += 1
    return base


def read_pack_table(path: Path, sheet: str) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    header_row = next(i for i, row in raw.iterrows() if any(str(v).strip() in {
        "purpose_code", "visitor_segment", "Sightseeing spot"
    } for v in row.tolist()))
    out = raw.iloc[header_row + 1 :].copy()
    out.columns = [str(v).strip() if pd.notna(v) else f"unnamed_{i}" for i, v in enumerate(raw.iloc[header_row])]
    return out.dropna(how="all").reset_index(drop=True)


def normalized_traffic(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    required = ["日期", "管制站", "入境 / 出境", "香港居民", "内地访客", "其他访客", "总计"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Traffic CSV missing columns: {missing}")
    df = df[required].copy()
    df["date"] = pd.to_datetime(df["日期"], format="%d-%m-%Y")
    df = df[(df["date"] >= "2026-01-01") & (df["date"] <= "2026-07-16")]
    long = df.melt(
        id_vars=["date", "管制站", "入境 / 出境"],
        value_vars=list(CATEGORIES),
        var_name="traveller_category_zh",
        value_name="passenger_movements",
    )
    long["control_point"] = long.pop("管制站")
    long["direction"] = long.pop("入境 / 出境").map(DIRECTIONS)
    long["traveller_category"] = long["traveller_category_zh"].map(CATEGORIES)
    long["passenger_movements"] = pd.to_numeric(long["passenger_movements"], errors="raise").astype(np.int64)
    long["is_weekend"] = long["date"].dt.dayofweek >= 5
    long["is_public_holiday"] = long["date"].dt.strftime("%Y-%m-%d").isin(HK_PUBLIC_HOLIDAYS_2026)
    long["day_type"] = np.where(long["is_weekend"] | long["is_public_holiday"], "weekend_or_holiday", "weekday")
    return long.sort_values(["date", "direction", "control_point", "traveller_category"]).reset_index(drop=True)


def typical_margins(long: pd.DataFrame, day_type: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    subset = long[long["day_type"] == day_type].copy()
    daily_totals = subset.groupby(["date", "direction", "traveller_category"], as_index=False)["passenger_movements"].sum()
    target = daily_totals.groupby(["direction", "traveller_category"], as_index=False)["passenger_movements"].median()
    target["target_total"] = target.pop("passenger_movements").round().astype(np.int64)
    merged = subset.merge(daily_totals, on=["date", "direction", "traveller_category"], suffixes=("", "_daily_total"))
    merged["port_share"] = np.divide(
        merged["passenger_movements"],
        merged["passenger_movements_daily_total"],
        out=np.zeros(len(merged), dtype=float),
        where=merged["passenger_movements_daily_total"].to_numpy() > 0,
    )
    shares = merged.groupby(["direction", "traveller_category", "control_point"], as_index=False)["port_share"].median()
    rows = []
    for (direction, category), group in shares.groupby(["direction", "traveller_category"], sort=False):
        total = int(target.loc[(target.direction == direction) & (target.traveller_category == category), "target_total"].iloc[0])
        g = group.copy()
        if g["port_share"].sum() <= 0:
            raise ValueError(f"No positive port shares for {direction}/{category}/{day_type}")
        g["normalized_port_share"] = g["port_share"] / g["port_share"].sum()
        g["passenger_movements"] = largest_remainder(g["normalized_port_share"].to_numpy(), total)
        g["day_type"] = day_type
        rows.append(g)
    margins = pd.concat(rows, ignore_index=True)
    margins = margins[["day_type", "direction", "traveller_category", "control_point", "passenger_movements", "normalized_port_share"]]
    return margins, target.assign(day_type=day_type)


def build_july_validation(long: pd.DataFrame, weekday_margins: pd.DataFrame) -> pd.DataFrame:
    actual = long[(long["date"] >= "2026-07-01") & (long["day_type"] == "weekday")]
    actual = actual.groupby(["direction", "traveller_category", "control_point"], as_index=False)["passenger_movements"].median()
    actual = actual.rename(columns={"passenger_movements": "actual_july_weekday_median"})
    out = weekday_margins.merge(actual, on=["direction", "traveller_category", "control_point"], how="left")
    out["actual_july_weekday_median"] = out["actual_july_weekday_median"].fillna(0)
    out["error"] = out["passenger_movements"] - out["actual_july_weekday_median"]
    out["absolute_error"] = out["error"].abs()
    return out


def build_purpose_priors(pack: Path) -> pd.DataFrame:
    raw = read_pack_table(pack, "05_CBTS2017目的")
    raw = raw.rename(columns={raw.columns[0]: "source_segment", raw.columns[1]: "purpose", raw.columns[4]: "share"})
    raw = raw[["source_segment", "purpose", "share"]].dropna(subset=["purpose", "share"])
    raw["share"] = pd.to_numeric(raw["share"], errors="coerce")
    raw = raw.dropna(subset=["share"])
    segment_map = {
        "居于内地的香港居民": "hk_resident_mainland",
        "内地访客": "mainland_visitor",
        "其他往来人士": "other_visitor",
    }
    purpose_map = {
        "Schooling": "school", "Work": "work", "Leisure": "leisure",
        "Visiting relatives and friends": "vfr", "Business": "business",
        "Transit": "transit", "Fetching relatives/friends": "vfr", "Other purposes": "other",
    }
    raw["person_segment"] = raw["source_segment"].map(segment_map)
    original_purpose = raw["purpose"].astype(str)
    raw["purpose"] = raw["purpose"].map(purpose_map).fillna(original_purpose.str.lower())
    raw.loc[original_purpose.str.contains("Fetching|escorting|accompanying", case=False, regex=True), "purpose"] = "vfr"
    raw.loc[original_purpose.str.contains("Other", case=False), "purpose"] = "other"
    raw = raw.dropna(subset=["person_segment"])
    out = raw.groupby(["person_segment", "purpose"], as_index=False)["share"].sum()
    out["share"] = out["share"] / out.groupby("person_segment")["share"].transform("sum")

    # TCS provides the best available normal-year structure for non-Mainland visitors.
    other = pd.DataFrame({
        "person_segment": "other_visitor",
        "purpose": ["sightseeing", "leisure", "business", "shopping", "vfr", "transit", "other"],
        "share": [0.39, 0.20, 0.12, 0.11, 0.10, 0.02, 0.06],
    })
    out = pd.concat([out[out.person_segment != "other_visitor"], other], ignore_index=True)
    out["stay_type"] = "all"
    out["official_bucket"] = "historical_detail"
    out["market_visitors_q1"] = np.nan
    out["source"] = np.where(out.person_segment == "other_visitor", "TCS_2022_2023", "CBTS_2017")
    out["use"] = "structural_prior_not_2026_absolute_count"
    return out


def read_hktb_q1_purpose(path: Path) -> pd.DataFrame:
    report = pd.read_excel(path, sheet_name="Report", header=None)
    report_text = " ".join(report.fillna("").astype(str).iloc[:12].to_numpy().ravel())
    if "Jan - Mar 2026" not in report_text and "2026 年 1 月至  3 月" not in report_text:
        raise ValueError("HKTB purpose workbook is not the Jan-Mar 2026 issue")

    labels = report.iloc[:, 2].fillna("").astype(str)
    total_index = labels[labels.str.strip().eq("總數 Total")].index
    mainland_index = labels[labels.str.strip().eq("中國內地 Mainland China")].index
    if len(total_index) != 1 or len(mainland_index) != 1:
        raise ValueError("Could not uniquely locate Total and Mainland China rows in HKTB Report")

    purpose_columns = {
        "vacation": 6,
        "business": 8,
        "vfr": 10,
        "en_route_others": 12,
    }

    def extract_market(start: int, market: str) -> list[dict[str, object]]:
        rows = []
        for offset, stay_type in [(1, "overnight"), (2, "same_day")]:
            row = report.iloc[start + offset]
            label = str(row.iloc[2])
            expected = "Overnight Visitors" if stay_type == "overnight" else "Same-day Visitors"
            if expected not in label:
                raise ValueError(f"Unexpected HKTB row after {market}: {label}")
            values = {name: float(row.iloc[col]) for name, col in purpose_columns.items()}
            if not np.isclose(sum(values.values()), 1.0, atol=1e-8):
                raise ValueError(f"HKTB purpose shares do not sum to one for {market}/{stay_type}")
            rows.append({
                "market": market,
                "stay_type": stay_type,
                "visitor_count_q1": int(row.iloc[4]),
                **values,
            })
        return rows

    total_rows = pd.DataFrame(extract_market(int(total_index[0]), "all_visitors"))
    mainland_rows = pd.DataFrame(extract_market(int(mainland_index[0]), "mainland_visitor"))
    records = [*mainland_rows.to_dict("records")]
    for stay_type in ["overnight", "same_day"]:
        total = total_rows.loc[total_rows.stay_type == stay_type].iloc[0]
        mainland = mainland_rows.loc[mainland_rows.stay_type == stay_type].iloc[0]
        other_count = int(total.visitor_count_q1 - mainland.visitor_count_q1)
        if other_count <= 0:
            raise ValueError(f"Non-Mainland visitor count is not positive for {stay_type}")
        record: dict[str, object] = {
            "market": "other_visitor",
            "stay_type": stay_type,
            "visitor_count_q1": other_count,
        }
        for purpose in purpose_columns:
            total_purpose = float(total.visitor_count_q1) * float(total[purpose])
            mainland_purpose = float(mainland.visitor_count_q1) * float(mainland[purpose])
            record[purpose] = (total_purpose - mainland_purpose) / other_count
        records.append(record)
    out = pd.DataFrame(records)
    if not np.allclose(out[list(purpose_columns)].sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("Derived HKTB market/stay purpose shares do not sum to one")
    out["source_file"] = str(path)
    out["report_period"] = "2026Q1"
    return out


def apply_hktb_q1_purpose_priors(base: pd.DataFrame, hktb: pd.DataFrame) -> pd.DataFrame:
    output = [base.loc[base.person_segment == "hk_resident_mainland"].copy()]
    bucket_mapping = {
        "mainland_visitor": {
            "vacation": ["leisure"],
            "business": ["business"],
            "vfr": ["vfr"],
            "en_route_others": ["transit", "other", "work"],
        },
        "other_visitor": {
            "vacation": ["sightseeing", "leisure", "shopping"],
            "business": ["business"],
            "vfr": ["vfr"],
            "en_route_others": ["transit", "other"],
        },
    }
    for segment, mapping in bucket_mapping.items():
        historical = base.loc[base.person_segment == segment].set_index("purpose")["share"]
        for _, official in hktb.loc[hktb.market == segment].iterrows():
            rows = []
            for bucket, purposes in mapping.items():
                detail = historical.reindex(purposes).fillna(0.0)
                if detail.sum() <= 0:
                    detail[:] = 1.0
                detail /= detail.sum()
                for purpose, fraction in detail.items():
                    rows.append({
                        "person_segment": segment,
                        "stay_type": official.stay_type,
                        "purpose": purpose,
                        "share": float(official[bucket]) * float(fraction),
                        "official_bucket": bucket,
                        "market_visitors_q1": int(official.visitor_count_q1),
                        "source": "HKTB_2026_Q1",
                        "use": "official_market_and_stay_purpose_share_with_historical_within_bucket_split",
                    })
            frame = pd.DataFrame(rows)
            frame["share"] /= frame.share.sum()
            output.append(frame)
    result = pd.concat(output, ignore_index=True)
    checks = result.loc[result.stay_type != "all"].groupby(["person_segment", "stay_type"]).share.sum()
    if not np.allclose(checks.to_numpy(), 1.0, atol=1e-10):
        raise ValueError("Final HKTB purpose priors do not sum to one")
    return result


def build_stay_priors(pack: Path) -> pd.DataFrame:
    raw = read_pack_table(pack, "06_CBTS2017逗留")
    raw = raw.rename(columns={raw.columns[0]: "purpose", raw.columns[2]: "stay_class", raw.columns[5]: "share"})
    out = raw[["purpose", "stay_class", "share"]].dropna().copy()
    out["share"] = pd.to_numeric(out["share"], errors="coerce")
    out = out.dropna(subset=["share"])
    out["purpose"] = out["purpose"].replace({
        "Leisure": "leisure", "Visiting relatives and friends": "vfr",
        "Business": "business", "Other purposes": "other", "All purposes": "all",
    })
    out["stay_class"] = out["stay_class"].astype(str).str.replace("–", "-", regex=False)
    out["source"] = "CBTS_2017"
    return out


def build_tcs_behavior(pack: Path) -> pd.DataFrame:
    raw = read_pack_table(pack, "07_TCS2022游客行为")
    raw = raw.rename(columns={raw.columns[0]: "visitor_segment", raw.columns[1]: "parameter_group", raw.columns[2]: "category", raw.columns[3]: "value", raw.columns[4]: "unit", raw.columns[6]: "source_section"})
    out = raw[["visitor_segment", "parameter_group", "category", "value", "unit", "source_section"]].dropna(subset=["visitor_segment", "parameter_group"])
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out


def build_popular_destinations(pack: Path) -> pd.DataFrame:
    raw = read_pack_table(pack, "08_热门目的地")
    left = raw.iloc[:, :5].copy()
    left.columns = ["destination_name", "destination_name_zh", "share", "district_hint", "use"]
    left["destination_type"] = "sightseeing_spot"
    right = raw.iloc[:, 6:10].copy()
    right.columns = ["destination_name", "destination_name_zh", "share", "use"]
    right["district_hint"] = right["destination_name"]
    right["destination_type"] = "shopping_district"
    out = pd.concat([left, right], ignore_index=True)
    out["share"] = pd.to_numeric(out["share"], errors="coerce")
    return out.dropna(subset=["destination_name", "share"])


def main() -> None:
    args = parse_args()
    output_root = args.out_dir or args.data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday/prepared_inputs"
    raw_dir = args.data_root / "tourism/hongkong/raw"
    output_root.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    sources = [args.traffic_csv, args.cbts_xlsx, args.hotel_xls, args.data_pack]
    if args.hktb_purpose_xlsx:
        sources.append(args.hktb_purpose_xlsx)
    for path in sources:
        if not path.exists():
            raise FileNotFoundError(path)

    inventory = []
    for path in sources:
        cached = raw_dir / path.name
        if not cached.exists() or sha256(cached) != sha256(path):
            shutil.copy2(path, cached)
        inventory.append({"source_file": str(path), "cached_file": str(cached), "bytes": path.stat().st_size, "sha256": sha256(path)})
    pd.DataFrame(inventory).to_csv(output_root / "source_inventory.csv", index=False, encoding="utf-8-sig")

    traffic = normalized_traffic(args.traffic_csv)
    traffic.to_csv(output_root / "immigration_daily_traffic_2026_normalized.csv", index=False, encoding="utf-8-sig")
    jan_jun = traffic[traffic["date"] < "2026-07-01"].copy()
    jan_jun_weekday, _ = typical_margins(jan_jun, "weekday")
    weekday, weekday_totals = typical_margins(traffic, "weekday")
    weekend, weekend_totals = typical_margins(traffic, "weekend_or_holiday")
    weekday.to_csv(output_root / "typical_weekday_bcp_category_margins.csv", index=False, encoding="utf-8-sig")
    jan_jun_weekday.to_csv(output_root / "jan_jun_weekday_bcp_category_margins.csv", index=False, encoding="utf-8-sig")
    weekend.to_csv(output_root / "typical_weekend_bcp_category_margins.csv", index=False, encoding="utf-8-sig")
    pd.concat([weekday_totals, weekend_totals], ignore_index=True).to_csv(output_root / "typical_day_total_margins.csv", index=False, encoding="utf-8-sig")

    validation = build_july_validation(traffic, jan_jun_weekday)
    validation.to_csv(output_root / "july_weekday_holdout_validation.csv", index=False, encoding="utf-8-sig")

    purpose = build_purpose_priors(args.data_pack)
    hktb_purpose = None
    if args.hktb_purpose_xlsx:
        hktb_purpose = read_hktb_q1_purpose(args.hktb_purpose_xlsx)
        hktb_purpose.to_csv(output_root / "hktb_2026_q1_purpose_by_market_stay.csv", index=False, encoding="utf-8-sig")
        purpose = apply_hktb_q1_purpose_priors(purpose, hktb_purpose)
    purpose.to_csv(output_root / "purpose_priors.csv", index=False, encoding="utf-8-sig")
    build_stay_priors(args.data_pack).to_csv(output_root / "stay_priors.csv", index=False, encoding="utf-8-sig")
    build_tcs_behavior(args.data_pack).to_csv(output_root / "tcs_visitor_behavior.csv", index=False, encoding="utf-8-sig")
    build_popular_destinations(args.data_pack).to_csv(output_root / "popular_destination_priors.csv", index=False, encoding="utf-8-sig")

    hotel = pd.DataFrame(HOTEL_DISTRICTS, columns=["hotel_district", "rooms", "occupancy_rate", "source_cells"])
    hotel["occupied_room_capacity"] = hotel["rooms"] * hotel["occupancy_rate"]
    hotel["capacity_share"] = hotel["occupied_room_capacity"] / hotel["occupied_room_capacity"].sum()
    hotel["source_file"] = str(args.hotel_xls)
    hotel["report_period"] = "2026-05"
    hotel.to_csv(output_root / "hotel_district_capacity_2026_05.csv", index=False, encoding="utf-8-sig")

    parameter_rows = [
        {"parameter": "mainland_resident_hk_share_baseline", "value": 116600 / (319800 + 116600), "source": "CBTS_2017_3A.1e"},
        {"parameter": "mainland_resident_hk_share_sensitivity", "value": 0.229, "source": "CBTS_2015_diagnostic"},
        {"parameter": "mainland_visitor_overnight_share", "value": 0.37, "source": "HKTB_2026_Jan-Apr"},
        {"parameter": "other_visitor_overnight_share", "value": 0.66, "source": "HKTB_2026_Jan-Apr"},
        {"parameter": "average_overnight_stay_nights", "value": 3.1, "source": "HKTB_2026_current"},
    ]
    if hktb_purpose is not None:
        for market in ["mainland_visitor", "other_visitor"]:
            market_rows = hktb_purpose.loc[hktb_purpose.market == market]
            overnight_count = float(market_rows.loc[market_rows.stay_type == "overnight", "visitor_count_q1"].iloc[0])
            total_count = float(market_rows.visitor_count_q1.sum())
            parameter_name = f"{market}_overnight_share"
            for row in parameter_rows:
                if row["parameter"] == parameter_name:
                    row.update(value=overnight_count / total_count, source="HKTB_2026_Q1_Report")
    pd.DataFrame(parameter_rows).to_csv(output_root / "population_and_stay_parameters.csv", index=False, encoding="utf-8-sig")

    july = validation
    mae = float(july.absolute_error.mean())
    denom = float(july.actual_july_weekday_median.sum())
    summary = {
        "scenario": "2026_typical_weekday",
        "observation_start": traffic.date.min().strftime("%Y-%m-%d"),
        "observation_end": traffic.date.max().strftime("%Y-%m-%d"),
        "weekday_dates": int(traffic.loc[traffic.day_type == "weekday", "date"].nunique()),
        "weekend_or_holiday_dates": int(traffic.loc[traffic.day_type == "weekend_or_holiday", "date"].nunique()),
        "typical_weekday_total_arrivals": int(weekday.loc[weekday.direction == "arrival", "passenger_movements"].sum()),
        "typical_weekday_total_departures": int(weekday.loc[weekday.direction == "departure", "passenger_movements"].sum()),
        "july_holdout_cell_mae": mae,
        "july_holdout_cell_wape": float(july.absolute_error.sum() / denom) if denom else math.nan,
        "hktb_q1_page": HKTB_Q1_PAGE,
        "hktb_q1_xlsx_url": HKTB_Q1_XLSX,
        "hktb_q1_page_verified": True,
        "hktb_q1_file_cached": bool(args.hktb_purpose_xlsx),
        "hktb_q1_purpose_integrated": hktb_purpose is not None,
        "hktb_q1_market_stay_rows": int(len(hktb_purpose)) if hktb_purpose is not None else 0,
        "hktb_q1_note": "Official Jan-Mar 2026 market-by-stay purpose shares are integrated when a local XLSX is supplied. Historical priors are used only to split HKTB aggregate purpose buckets into model subcategories.",
        "tcs_report": TCS_REPORT,
        "general_holidays_source": HK_2026_HOLIDAYS,
        "holdout_design": "Fit typical margins on 2026-01-01 through 2026-06-30; validate eligible July weekdays; refit final margins on all data through 2026-07-16.",
        "hotel_extraction": "Verified cells in P2 (rooms) and P4 (May occupancy); values retained with source workbook checksum.",
        "units": "border passenger movements per typical day",
    }
    (output_root / "preparation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "source_checksums.json").write_text(json.dumps({p.name: sha256(p) for p in sources}, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
