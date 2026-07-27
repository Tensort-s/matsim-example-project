#!/usr/bin/env python3
"""Extract Hong Kong 2021 Census commute tables 7.8 and 7.9 to CSV."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import fitz
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PDF = Path(r"D:\Program Files\21c-summary-results.pdf")
DEFAULT_OUT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "census_2021_commute_constraints"
)

RESIDENCE_AREAS_4 = [
    ("hong_kong_island", "香港島", "Hong Kong Island"),
    ("kowloon", "九龍", "Kowloon"),
    ("new_towns", "新市鎮", "New towns"),
    ("other_nt_marine", "新界其他地區及水上", "Other areas in the New Territories and Marine"),
]
RESIDENCE_AREAS_3 = [
    ("hong_kong_island", "香港島", "Hong Kong Island"),
    ("kowloon", "九龍", "Kowloon"),
    ("new_territories", "新界", "New Territories"),
]
RES4_TO_RES3 = {
    "hong_kong_island": "hong_kong_island",
    "kowloon": "kowloon",
    "new_towns": "new_territories",
    "other_nt_marine": "new_territories",
}

TABLE_7_9_ROWS = [
    ("mtr_local", "香港鐵路（本地線）", "Mass Transit Railway (Local line)", [185069, 380249, 541708, 43074, 1150100], [7.0, 14.3, 20.4, 1.6, 43.2]),
    ("bus", "巴士", "Bus", [105337, 180617, 354022, 23709, 663685], [4.0, 6.8, 13.3, 0.9, 25.0]),
    ("on_foot", "步行", "On foot only", [54750, 94759, 121173, 8311, 278993], [2.1, 3.6, 4.6, 0.3, 10.5]),
    ("private_car_passenger_van", "私家車／客貨車", "Private car/ Passenger van", [35559, 37574, 88202, 28556, 189891], [1.3, 1.4, 3.3, 1.1, 7.1]),
    ("public_light_bus", "公共小巴", "Public light bus", [21510, 48989, 63819, 14901, 149219], [0.8, 1.8, 2.4, 0.6, 5.6]),
    ("company_bus_van", "公司巴士／小巴", "Company bus/ van", [8765, 15431, 36826, 2011, 63033], [0.3, 0.6, 1.4, 0.1, 2.4]),
    ("mtr_light_rail", "香港鐵路（輕鐵）", "Mass Transit Railway (Light Rail)", [0, 0, 44255, 1621, 45876], [0.0, 0.0, 1.7, 0.1, 1.7]),
    ("taxi", "的士", "Taxi", [15641, 10667, 10613, 936, 37857], [0.6, 0.4, 0.4, 0.0, 1.4]),
    ("residential_coach", "屋邨／大廈巴士", "Residential coach service", [2860, 3324, 14092, 2041, 22317], [0.1, 0.1, 0.5, 0.1, 0.8]),
    ("ferry_vessel", "小輪／船艇", "Ferry/ Vessel", [2420, 2651, 2349, 13655, 21075], [0.1, 0.1, 0.1, 0.5, 0.8]),
    ("others", "其他", "Others", [12299, 4812, 17338, 3063, 37512], [0.5, 0.2, 0.7, 0.1, 1.4]),
    ("total", "總計", "Total", [444210, 779073, 1294397, 141878, 2659558], [16.7, 29.3, 48.7, 5.3, 100.0]),
]

TABLE_7_8_FIXED_ROWS = [
    ("same_district", "同區工作", "Work in the same district", "same_area", [146419, 178077, 244525, 17166, 586187], [4.0, 4.8, 6.6, 0.5, 15.9]),
    ("work_hong_kong_island", "香港島", "Hong Kong Island", "hong_kong_island", [171273, 201077, 251755, 33208, 657313], [4.7, 5.5, 6.8, 0.9, 17.9]),
    ("work_kowloon", "九龍", "Kowloon", "kowloon", [88058, 247133, 381026, 39819, 756036], [2.4, 6.7, 10.4, 1.1, 20.5]),
    ("work_new_towns", "新市鎮", "New towns", "new_towns", [29412, 122200, 316798, 44992, 513402], [0.8, 3.3, 8.6, 1.2, 13.9]),
    ("work_other_nt", "新界其他地區", "Other areas in the New Territories", "other_nt_marine", [9048, 30586, 100293, 6693, 146620], [0.2, 0.8, 2.7, 0.2, 4.0]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="2021 Census summary PDF.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory.")
    return parser.parse_args()


def pdf_page_text(pdf: Path, page_index: int) -> str:
    with fitz.open(pdf) as doc:
        return doc[page_index].get_text()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def assert_pdf_contains_values(pdf: Path) -> None:
    page_78 = compact(pdf_page_text(pdf, 115))
    page_79 = compact(pdf_page_text(pdf, 116))
    required = [
        ("表7.8", page_78),
        ("Workingpopulationbyplaceofworkandareaofresidence,2021", page_78),
        ("表7.9", page_79),
        ("WorkingpopulationwithfixedplaceofworkinHongKongbymainmodeoftransport", page_79),
        ("2659558", page_79),
        ("1150100", page_79),
        ("663685", page_79),
        ("3631984", page_78),
        ("597140", page_78),
        ("375286", page_78),
    ]
    for needle, haystack in required:
        if needle not in haystack:
            raise ValueError(f"Expected PDF text fragment not found: {needle}")


def table_7_9_tidy() -> pd.DataFrame:
    rows = []
    for mode_order, (mode_code, mode_zh, mode_en, workers, percents) in enumerate(TABLE_7_9_ROWS):
        for area_order, (area_code, area_zh, area_en) in enumerate(RESIDENCE_AREAS_4):
            rows.append(
                {
                    "table": "7.9",
                    "mode_order": mode_order,
                    "mode_code": mode_code,
                    "mode_zh": mode_zh,
                    "mode_en": mode_en,
                    "residence_area_4_code": area_code,
                    "residence_area_4_zh": area_zh,
                    "residence_area_4_en": area_en,
                    "residence_area_3_code": RES4_TO_RES3[area_code],
                    "workers": workers[area_order],
                    "percent_total": percents[area_order],
                }
            )
        rows.append(
            {
                "table": "7.9",
                "mode_order": mode_order,
                "mode_code": mode_code,
                "mode_zh": mode_zh,
                "mode_en": mode_en,
                "residence_area_4_code": "total",
                "residence_area_4_zh": "總計",
                "residence_area_4_en": "Total",
                "residence_area_3_code": "total",
                "workers": workers[4],
                "percent_total": percents[4],
            }
        )
    return pd.DataFrame(rows)


def table_7_8_tidy() -> pd.DataFrame:
    rows = []
    for row_order, (row_code, workplace_zh, workplace_en, workplace_code, workers, percents) in enumerate(TABLE_7_8_FIXED_ROWS):
        for area_order, (area_code, area_zh, area_en) in enumerate(RESIDENCE_AREAS_4):
            rows.append(
                {
                    "table": "7.8",
                    "row_order": row_order,
                    "workplace_row_code": row_code,
                    "workplace_area_code": workplace_code,
                    "workplace_area_zh": workplace_zh,
                    "workplace_area_en": workplace_en,
                    "residence_area_4_code": area_code,
                    "residence_area_4_zh": area_zh,
                    "residence_area_4_en": area_en,
                    "residence_area_3_code": RES4_TO_RES3[area_code],
                    "workers": workers[area_order],
                    "percent_total": percents[area_order],
                }
            )
        rows.append(
            {
                "table": "7.8",
                "row_order": row_order,
                "workplace_row_code": row_code,
                "workplace_area_code": workplace_code,
                "workplace_area_zh": workplace_zh,
                "workplace_area_en": workplace_en,
                "residence_area_4_code": "total",
                "residence_area_4_zh": "總計",
                "residence_area_4_en": "Total",
                "residence_area_3_code": "total",
                "workers": workers[4],
                "percent_total": percents[4],
            }
        )
    return pd.DataFrame(rows)


def build_target_3area(table78: pd.DataFrame) -> pd.DataFrame:
    area_codes = [code for code, _, _ in RESIDENCE_AREAS_3]
    target = {(origin, destination): 0 for origin in area_codes for destination in area_codes}
    subset = table78[table78["residence_area_4_code"] != "total"].copy()
    for row in subset.itertuples(index=False):
        origin = row.residence_area_3_code
        if row.workplace_area_code == "same_area":
            destination = origin
            target[(origin, destination)] += int(row.workers)
        else:
            destination = RES4_TO_RES3[row.workplace_area_code]
            target[(origin, destination)] += int(row.workers)
    rows = []
    labels = {code: en for code, _, en in RESIDENCE_AREAS_3}
    for origin in area_codes:
        for destination in area_codes:
            rows.append(
                {
                    "residence_area_code": origin,
                    "residence_area_en": labels[origin],
                    "workplace_area_code": destination,
                    "workplace_area_en": labels[destination],
                    "workers": int(target[(origin, destination)]),
                }
            )
    return pd.DataFrame(rows)


def build_target_4area(table78: pd.DataFrame) -> pd.DataFrame:
    area_codes = [code for code, _, _ in RESIDENCE_AREAS_4]
    target = {(origin, destination): 0 for origin in area_codes for destination in area_codes}
    subset = table78[table78["residence_area_4_code"] != "total"].copy()
    for row in subset.itertuples(index=False):
        origin = row.residence_area_4_code
        if row.workplace_area_code == "same_area":
            destination = origin
        else:
            destination = row.workplace_area_code
        target[(origin, destination)] += int(row.workers)
    rows = []
    labels = {code: en for code, _, en in RESIDENCE_AREAS_4}
    labels_zh = {code: zh for code, zh, _ in RESIDENCE_AREAS_4}
    for origin in area_codes:
        for destination in area_codes:
            rows.append(
                {
                    "residence_area_code": origin,
                    "residence_area_en": labels[origin],
                    "residence_area_zh": labels_zh[origin],
                    "workplace_area_code": destination,
                    "workplace_area_en": labels[destination],
                    "workplace_area_zh": labels_zh[destination],
                    "workers": int(target[(origin, destination)]),
                }
            )
    return pd.DataFrame(rows)


def validate(table79: pd.DataFrame, target3: pd.DataFrame, target4: pd.DataFrame) -> dict:
    total79 = int(table79[(table79["mode_code"] == "total") & (table79["residence_area_4_code"] == "total")]["workers"].iloc[0])
    if total79 != 2_659_558:
        raise ValueError(f"Unexpected table 7.9 total: {total79}")

    residence_4 = (
        table79[(table79["mode_code"] == "total") & (table79["residence_area_4_code"] != "total")]
        .groupby("residence_area_4_code", as_index=False)["workers"]
        .sum()
    )
    expected4 = {
        "hong_kong_island": 444210,
        "kowloon": 779073,
        "new_towns": 1294397,
        "other_nt_marine": 141878,
    }
    got4 = dict(zip(residence_4["residence_area_4_code"], residence_4["workers"]))
    if got4 != expected4:
        raise ValueError(f"Unexpected 7.9 residence 4-area margins: {got4}")

    residence_3 = (
        table79[(table79["mode_code"] == "total") & (table79["residence_area_4_code"] != "total")]
        .groupby("residence_area_3_code", as_index=False)["workers"]
        .sum()
    )
    expected = {"hong_kong_island": 444210, "kowloon": 779073, "new_territories": 1436275}
    got = dict(zip(residence_3["residence_area_3_code"], residence_3["workers"]))
    if got != expected:
        raise ValueError(f"Unexpected 7.9 residence 3-area margins: {got}")

    mode_totals = dict(
        zip(
            table79[table79["residence_area_4_code"] == "total"]["mode_code"],
            table79[table79["residence_area_4_code"] == "total"]["workers"],
        )
    )
    if mode_totals["mtr_local"] != 1_150_100 or mode_totals["bus"] != 663_685:
        raise ValueError(f"Unexpected key mode totals: {mode_totals}")

    target4_total = int(target4["workers"].sum())
    if target4_total != 2_659_558:
        raise ValueError(f"Unexpected 7.8 4-area fixed-workplace target total: {target4_total}")

    target4_origin = target4.groupby("residence_area_code")["workers"].sum().to_dict()
    if target4_origin != expected4:
        raise ValueError(f"7.8 4-area origin margins do not match 7.9: {target4_origin} vs {expected4}")

    target_total = int(target3["workers"].sum())
    if target_total != 2_659_558:
        raise ValueError(f"Unexpected 7.8 3-area fixed-workplace target total: {target_total}")

    target_origin = target3.groupby("residence_area_code")["workers"].sum().to_dict()
    if target_origin != expected:
        raise ValueError(f"7.8 target origin margins do not match 7.9: {target_origin} vs {expected}")

    return {
        "table_7_9_total": total79,
        "table_7_9_residence_4area_margins": expected4,
        "table_7_9_residence_3area_margins": expected,
        "table_7_9_mtr_local_total": int(mode_totals["mtr_local"]),
        "table_7_9_bus_total": int(mode_totals["bus"]),
        "table_7_8_target_4area_total": target4_total,
        "table_7_8_target_4area_origin_margins": {key: int(value) for key, value in target4_origin.items()},
        "table_7_8_target_3area_total": target_total,
        "table_7_8_target_3area_origin_margins": {key: int(value) for key, value in target_origin.items()},
    }


def main() -> None:
    args = parse_args()
    if not args.pdf.exists():
        raise FileNotFoundError(args.pdf)
    assert_pdf_contains_values(args.pdf)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    table79 = table_7_9_tidy()
    table78 = table_7_8_tidy()
    target4 = build_target_4area(table78)
    target3 = build_target_3area(table78)
    qa = validate(table79, target3, target4)

    t79_path = args.out_dir / "table_7_9_commute_mode_by_residence.csv"
    table79.to_csv(t79_path, index=False, encoding="utf-8-sig")

    wide = table79.pivot_table(
        index=["mode_order", "mode_code", "mode_zh", "mode_en"],
        columns="residence_area_4_code",
        values="workers",
        aggfunc="first",
    ).reset_index()
    wide_path = args.out_dir / "table_7_9_commute_mode_by_residence_wide.csv"
    wide.to_csv(wide_path, index=False, encoding="utf-8-sig")

    t78_path = args.out_dir / "table_7_8_workplace_by_residence.csv"
    table78.to_csv(t78_path, index=False, encoding="utf-8-sig")

    target4_path = args.out_dir / "census_2021_area_od_target_4area.csv"
    target4.to_csv(target4_path, index=False, encoding="utf-8-sig")

    target3_path = args.out_dir / "census_2021_area_od_target_3area.csv"
    target3.to_csv(target3_path, index=False, encoding="utf-8-sig")

    summary = {
        "source_pdf": str(args.pdf),
        "pdf_pages": {"table_7_8_page_index_0_based": 115, "table_7_9_page_index_0_based": 116},
        "outputs": {
            "table_7_9_tidy": str(t79_path),
            "table_7_9_wide": str(wide_path),
            "table_7_8_tidy": str(t78_path),
            "census_2021_area_od_target_4area": str(target4_path),
            "census_2021_area_od_target_3area": str(target3_path),
        },
        "qa": qa,
        "notes": [
            "Table 7.9 contains residence area by main mode, not workplace destination.",
            "Table 7.8 fixed-workplace rows are used to build the 4-area residence-to-workplace target matrix.",
            "The 4-area output keeps New towns separate from Other areas in the New Territories and Marine.",
            "The 3-area output is retained only as a backward-compatible aggregate.",
        ],
    }
    summary_path = args.out_dir / "census_2021_commute_table_extraction_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {t79_path}")
    print(f"Wrote: {wide_path}")
    print(f"Wrote: {t78_path}")
    print(f"Wrote: {target4_path}")
    print(f"Wrote: {target3_path}")
    print(f"Wrote: {summary_path}")
    print(json.dumps(qa, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
