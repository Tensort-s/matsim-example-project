"""Build Hong Kong immigration control point location tables.

The script combines the CSDI Control Points point layer maintained by the
Immigration Department with the daily passenger traffic CSV for a selected
date.  It keeps CSDI as the authoritative location source and treats passenger
traffic names as statistical categories.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import ssl
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[3]

CSDI_DATASET_ID = "immd_rcd_1633320081376_19895"
CSDI_LAYER_NAME = "CP"
CSDI_FILE_API = (
    "https://portal.csdi.gov.hk/csdi-webpage/file-api"
    f"?dataset_id={CSDI_DATASET_ID}&format=geojson&layer_name={CSDI_LAYER_NAME}"
)
CSDI_METADATA_API = (
    "https://portal.csdi.gov.hk/geoportal/rest/metadata/item/"
    f"{CSDI_DATASET_ID}/xml"
)
CSDI_DATASET_INFO_API = (
    "https://portal.csdi.gov.hk/csdi-webpage/getDatasetInfo"
    f"?datasetId={CSDI_DATASET_ID}"
)
IMMD_CONTROL_POINT_PAGE = "https://www.immd.gov.hk/hks/contactus/control_points.html"
IMMD_DAILY_TRAFFIC_OPEN_DATA = (
    "https://www.immd.gov.hk/opendata/hks/transport/"
    "immigration_clearance/statistics_on_daily_passenger_traffic.csv"
)

DEFAULT_TRAFFIC_CSV = Path(
    r"D:\Program Files\statistics_on_daily_passenger_traffic.csv"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "border" / "hongkong" / "control_points"
)


CP_TO_TRAFFIC_CATEGORY = {
    "Airport Control Point (Terminal 1)": ("机场", "airport_terminal_category"),
    "Airport Control Point (Terminal 2)": ("机场", "airport_terminal_category"),
    "Lo Wu Control Point": ("罗湖", "direct"),
    "Lok Ma Chau Control Point": ("落马洲", "direct"),
    "Lok Ma Chau Spur Line Control Point": ("落马洲支线", "direct"),
    "Man Kam To Control Point": ("文锦渡", "direct"),
    "Sha Tau Kok Control Point": ("沙头角", "direct"),
    "China Ferry Terminal Control Point": ("中国客运码头", "direct"),
    "Macao Ferry Terminal Control Point": ("港澳客轮码头", "direct"),
    "Shenzhen Bay Control Point": ("深圳湾", "direct"),
    "Kai Tak Cruise Terminal Control Point": ("启德邮轮码头", "direct"),
    "Express Rail Link West Kowloon Control Point": ("高铁西九龙", "direct"),
    "Hong Kong-Zhuhai-Macao Bridge Control Point": ("港珠澳大桥", "direct"),
    "Heung Yuen Wai Control Point": ("香园围", "direct"),
    "Harbour Control": ("港口管制", "port_aggregate_category"),
    "River Trade Terminal Control Point": ("港口管制", "port_related_not_named_in_daily_csv"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="16-07-2026", help="CSV date, dd-mm-yyyy.")
    parser.add_argument(
        "--traffic-csv",
        type=Path,
        default=DEFAULT_TRAFFIC_CSV,
        help="Local statistics_on_daily_passenger_traffic.csv.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for government map endpoints.",
    )
    return parser.parse_args()


def fetch_text(url: str, insecure: bool = False) -> str:
    ctx = ssl._create_unverified_context() if insecure else None
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, context=ctx, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def download_geojson(insecure: bool = False) -> dict:
    return json.loads(fetch_text(CSDI_FILE_API, insecure=insecure))


def clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "; ", value or "", flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def read_daily_traffic(path: Path, target_date: str) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row["日期"] != target_date:
                continue
            control_point = row["管制站"]
            direction = row["入境 / 出境"]
            prefix = "arrival" if direction == "入境" else "departure"
            for src_col, out_col in [
                ("香港居民", "hk_residents"),
                ("内地访客", "mainland_visitors"),
                ("其他访客", "other_visitors"),
                ("总计", "total"),
            ]:
                value = int((row[src_col] or "0").replace(",", ""))
                totals[control_point][f"{prefix}_{out_col}"] += value
                totals[control_point][f"both_{out_col}"] += value
    return {key: dict(value) for key, value in totals.items()}


def feature_to_row(feature: dict, traffic: dict[str, dict[str, int]], target_date: str) -> dict:
    props = feature["properties"]
    name_en = props["NAME_EN"]
    traffic_category, match_type = CP_TO_TRAFFIC_CATEGORY.get(name_en, ("", "unmatched"))
    traffic_totals = traffic.get(traffic_category, {})
    coords = feature["geometry"]["coordinates"]
    note = {
        "direct": "Direct one-to-one match to the daily traffic statistical category.",
        "airport_terminal_category": (
            "Daily traffic CSV reports Airport as one aggregate category; "
            "do not add Terminal 1 and Terminal 2 rows together."
        ),
        "port_aggregate_category": (
            "Daily traffic CSV reports Harbour Control as 港口管制; this row is "
            "the Central Government Pier control point."
        ),
        "port_related_not_named_in_daily_csv": (
            "CSDI has this as a separate control point, but the daily passenger "
            f"CSV has no named River Trade Terminal row on {target_date}."
        ),
        "unmatched": "No passenger traffic category mapping was defined.",
    }[match_type]
    return {
        "as_of_date": target_date,
        "csdi_dataset_id": CSDI_DATASET_ID,
        "csdi_layer": CSDI_LAYER_NAME,
        "name_en": name_en,
        "name_tc": props.get("NAME_TC", ""),
        "traffic_csv_category": traffic_category,
        "traffic_match_type": match_type,
        "traffic_category_present_on_date": str(traffic_category in traffic).lower(),
        "traffic_category_total_both_directions": traffic_totals.get("both_total", ""),
        "traffic_category_arrival_total": traffic_totals.get("arrival_total", ""),
        "traffic_category_departure_total": traffic_totals.get("departure_total", ""),
        "traffic_category_hk_residents_both": traffic_totals.get("both_hk_residents", ""),
        "traffic_category_mainland_visitors_both": traffic_totals.get(
            "both_mainland_visitors", ""
        ),
        "traffic_category_other_visitors_both": traffic_totals.get(
            "both_other_visitors", ""
        ),
        "longitude": f"{float(coords[0]):.8f}",
        "latitude": f"{float(coords[1]):.8f}",
        "easting_hk1980": props.get("EASTING", ""),
        "northing_hk1980": props.get("NORTHING", ""),
        "address_en": props.get("ADDRESS_EN", ""),
        "address_tc": props.get("ADDRESS_TC", ""),
        "opening_hours_en": clean_html(props.get("NSEARCH01_EN", "")),
        "opening_hours_tc": clean_html(props.get("NSEARCH01_TC", "")),
        "lastupdate": props.get("LASTUPDATE", ""),
        "location_source_url": CSDI_FILE_API,
        "traffic_source_url": IMMD_DAILY_TRAFFIC_OPEN_DATA,
        "notes": note,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_traffic_match_rows(
    traffic: dict[str, dict[str, int]], location_rows: list[dict], target_date: str
) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in location_rows:
        grouped[row["traffic_csv_category"]].append(row)
    output = []
    for category in sorted(traffic):
        rows = grouped.get(category, [])
        output.append(
            {
                "date": target_date,
                "traffic_csv_category": category,
                "traffic_total_both_directions": traffic[category].get("both_total", 0),
                "traffic_arrival_total": traffic[category].get("arrival_total", 0),
                "traffic_departure_total": traffic[category].get("departure_total", 0),
                "matched_location_count": len(rows),
                "matched_location_names_en": " | ".join(r["name_en"] for r in rows),
                "matched_location_names_tc": " | ".join(r["name_tc"] for r in rows),
                "matched_longitudes": " | ".join(r["longitude"] for r in rows),
                "matched_latitudes": " | ".join(r["latitude"] for r in rows),
                "match_notes": " | ".join(r["notes"] for r in rows),
            }
        )
    return output


def write_markdown(
    path: Path,
    target_date: str,
    location_rows: list[dict],
    traffic_rows: list[dict],
    dataset_info_text: str,
) -> None:
    dataset_info = json.loads(dataset_info_text)
    record_count = dataset_info["datasetInfo"]["sdsJsonList"][0]["recordCount"]
    lines = [
        "# Hong Kong Immigration Control Point Locations",
        "",
        f"整理日期口径：`{target_date}`（来自每日出入境人次统计 CSV）。",
        "",
        "## Sources",
        "",
        f"- CSDI Control Points GeoJSON: `{CSDI_FILE_API}`",
        f"- CSDI metadata XML: `{CSDI_METADATA_API}`",
        f"- CSDI dataset info API reports `{record_count}` point records.",
        f"- Immigration Department control point page: `{IMMD_CONTROL_POINT_PAGE}`",
        f"- Daily passenger traffic CSV: `{IMMD_DAILY_TRAFFIC_OPEN_DATA}`",
        "",
        "## Outputs",
        "",
        "- `hong_kong_control_point_locations_2026-07-16.csv`: 16 CSDI control point locations with matched passenger traffic categories.",
        "- `hong_kong_daily_traffic_control_point_match_2026-07-16.csv`: 2026-07-16 traffic CSV categories and their matched locations.",
        "- `hong_kong_control_points_csdi_20260622.geojson`: raw CSDI point layer downloaded through the file API.",
        "",
        "## Matching Notes",
        "",
        "- `机场` is an aggregate passenger traffic category. CSDI has separate Terminal 1 and Terminal 2 points; the traffic total is repeated for reference and must not be summed across both rows.",
        "- `港口管制` is also an aggregate/statistical category. CSDI includes `Harbour Control` and `River Trade Terminal Control Point`; the River Trade Terminal point has no separately named 2026-07-16 row in the passenger CSV.",
        "- `沙头角` is retained as a location because it exists in both the CSDI layer and daily CSV, but its clearance service is suspended and its 2026-07-16 passenger total is zero.",
        "",
        "## QA",
        "",
        f"- CSDI location rows written: `{len(location_rows)}`.",
        f"- Passenger traffic categories on `{target_date}`: `{len(traffic_rows)}`.",
        f"- Total daily traffic across CSV categories: `{sum(int(r['traffic_total_both_directions']) for r in traffic_rows):,}`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    geojson = download_geojson(insecure=args.insecure)
    traffic = read_daily_traffic(args.traffic_csv, args.date)
    if not traffic:
        raise ValueError(f"No passenger traffic rows found for {args.date}")

    location_rows = [
        feature_to_row(feature, traffic, args.date) for feature in geojson["features"]
    ]
    location_rows.sort(key=lambda row: (row["traffic_csv_category"], row["name_en"]))
    traffic_rows = build_traffic_match_rows(traffic, location_rows, args.date)

    date_token = datetime.strptime(args.date, "%d-%m-%Y").strftime("%Y-%m-%d")
    raw_geojson_path = args.output_dir / "hong_kong_control_points_csdi_20260622.geojson"
    location_csv_path = (
        args.output_dir / f"hong_kong_control_point_locations_{date_token}.csv"
    )
    traffic_csv_path = (
        args.output_dir
        / f"hong_kong_daily_traffic_control_point_match_{date_token}.csv"
    )
    markdown_path = (
        args.output_dir / f"hong_kong_control_point_locations_{date_token}.md"
    )

    raw_geojson_path.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(location_csv_path, location_rows)
    write_csv(traffic_csv_path, traffic_rows)
    dataset_info_text = fetch_text(CSDI_DATASET_INFO_API, insecure=args.insecure)
    write_markdown(
        markdown_path,
        args.date,
        location_rows,
        traffic_rows,
        dataset_info_text,
    )

    summary = {
        "date": args.date,
        "csdi_feature_count": len(geojson["features"]),
        "traffic_category_count": len(traffic),
        "traffic_total_both_directions": sum(
            item.get("both_total", 0) for item in traffic.values()
        ),
        "outputs": {
            "geojson": str(raw_geojson_path),
            "location_csv": str(location_csv_path),
            "traffic_match_csv": str(traffic_csv_path),
            "markdown": str(markdown_path),
        },
    }
    (args.output_dir / f"hong_kong_control_point_locations_{date_token}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
