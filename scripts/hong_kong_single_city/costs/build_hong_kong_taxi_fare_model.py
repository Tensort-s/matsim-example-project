#!/usr/bin/env python3
"""Build machine-readable Hong Kong taxi fare and surcharge rules."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = WINDOWS_ROOT if WINDOWS_ROOT.exists() else ROOT
RAW_DIR = PROJECT_ROOT / "data/taxi/hongkong/raw/official_fare_sources_2026"
OUT_DIR = PROJECT_ROOT / "data/taxi/hongkong/processed/taxi_fare_model_v1"
DOWNLOAD_DATE = date.today().isoformat()

SOURCE_URLS = {
    "td_taxi_fare_of_hong_kong.html": "https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/taxi/taxi_fare_of_hong_kong/index.html",
    "td_taxi_operating_areas.html": "https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/taxi/details_of_taxi_operating_areas_/",
    "td_road_tunnel_toll_rates.html": "https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/toll_matters/toll_rates_of_road_tunnels_and_lantau_link/index.html",
    "td_road_harbour_crossing_tvt.html": "https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/tvt/index.html",
    "td_tai_lam_tunnel_tvt.html": "https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/tlt/index.html",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--force-download", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_sources(raw_dir: Path, force: bool) -> list[dict[str, object]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for file_name, url in SOURCE_URLS.items():
        path = raw_dir / file_name
        if force or not path.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            path.write_bytes(response.content)
        rows.append(
            {
                "file_name": file_name,
                "project_path": path.as_posix(),
                "source_url": url,
                "source_download_date": DOWNLOAD_DATE,
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return rows


def fare_rules(download_date: str) -> pd.DataFrame:
    source_url = SOURCE_URLS["td_taxi_fare_of_hong_kong.html"]
    rows = [
        {
            "taxi_type": "urban_taxi",
            "fare_effective_date": "2024-07-14",
            "flagfall_distance_m": 2000,
            "flagfall_hkd": 29.0,
            "first_tier_end_fare_hkd": 102.5,
            "first_tier_end_distance_m": 9000,
            "first_tier_increment_distance_m": 200,
            "first_tier_increment_hkd": 2.1,
            "second_tier_increment_distance_m": 200,
            "second_tier_increment_hkd": 1.4,
            "waiting_increment_seconds": 60,
            "waiting_increment_hkd": 2.1,
            "second_tier_waiting_increment_hkd": 1.4,
            "booking_fee_hkd": 5.0,
            "baggage_fee_hkd": 6.0,
        },
        {
            "taxi_type": "new_territories_taxi",
            "fare_effective_date": "2024-07-14",
            "flagfall_distance_m": 2000,
            "flagfall_hkd": 25.5,
            "first_tier_end_fare_hkd": 82.5,
            "first_tier_end_distance_m": 8000,
            "first_tier_increment_distance_m": 200,
            "first_tier_increment_hkd": 1.9,
            "second_tier_increment_distance_m": 200,
            "second_tier_increment_hkd": 1.4,
            "waiting_increment_seconds": 60,
            "waiting_increment_hkd": 1.9,
            "second_tier_waiting_increment_hkd": 1.4,
            "booking_fee_hkd": 5.0,
            "baggage_fee_hkd": 6.0,
        },
        {
            "taxi_type": "lantau_taxi",
            "fare_effective_date": "2024-07-14",
            "flagfall_distance_m": 2000,
            "flagfall_hkd": 24.0,
            "first_tier_end_fare_hkd": 195.0,
            "first_tier_end_distance_m": 20000,
            "first_tier_increment_distance_m": 200,
            "first_tier_increment_hkd": 1.9,
            "second_tier_increment_distance_m": 200,
            "second_tier_increment_hkd": 1.6,
            "waiting_increment_seconds": 60,
            "waiting_increment_hkd": 1.9,
            "second_tier_waiting_increment_hkd": 1.6,
            "booking_fee_hkd": 5.0,
            "baggage_fee_hkd": 6.0,
        },
    ]
    frame = pd.DataFrame(rows)
    frame["source_file"] = "td_taxi_fare_of_hong_kong.html"
    frame["source_url"] = source_url
    frame["source_download_date"] = download_date
    frame["currency"] = "HKD"
    frame["discrete_rule_note"] = (
        "First 2 kilometres or any part thereof are covered by flagfall; "
        "each subsequent 200 metres or part thereof is charged by ceiling."
    )
    return frame


def tunnel_rules(download_date: str) -> pd.DataFrame:
    fare_url = SOURCE_URLS["td_taxi_fare_of_hong_kong.html"]
    rhc_url = SOURCE_URLS["td_road_harbour_crossing_tvt.html"]
    tai_lam_url = SOURCE_URLS["td_tai_lam_tunnel_tvt.html"]
    rows = [
        ("cross_harbour_tunnel", "Cross-Harbour Tunnel", "urban_taxi", 50.0, "taxi passenger pays outbound $25 plus return $25 unless exception applies", rhc_url),
        ("eastern_harbour_crossing", "Eastern Harbour Crossing", "urban_taxi", 50.0, "taxi passenger pays outbound $25 plus return $25 unless exception applies", rhc_url),
        ("western_harbour_crossing", "Western Harbour Crossing", "urban_taxi", 50.0, "taxi passenger pays outbound $25 plus return $25 unless exception applies", rhc_url),
        ("tai_lam_tunnel", "Tai Lam Tunnel", "urban_taxi", 28.0, "taxi passenger surcharge from TD taxi fare table", tai_lam_url),
        ("tates_cairn_tunnel", "Tate's Cairn Tunnel", "urban_taxi", 20.0, "taxi passenger surcharge from TD taxi fare table", fare_url),
        ("aberdeen_tunnel", "Aberdeen Tunnel", "urban_taxi", 8.0, "taxi passenger surcharge from TD taxi fare table", fare_url),
        ("shing_mun_tunnels", "Shing Mun Tunnels", "urban_taxi", 8.0, "taxi passenger surcharge from TD taxi fare table", fare_url),
        ("lion_rock_tunnel", "Lion Rock Tunnel", "urban_taxi", 8.0, "taxi passenger surcharge from TD taxi fare table", fare_url),
        ("tsing_sha_control_area", "Tsing Sha Control Area", "urban_taxi", 8.0, "taxi passenger surcharge from TD taxi fare table", fare_url),
        ("tai_lam_tunnel", "Tai Lam Tunnel", "new_territories_taxi", 28.0, "taxi passenger surcharge from TD taxi fare table", tai_lam_url),
        ("shing_mun_tunnels", "Shing Mun Tunnels", "new_territories_taxi", 8.0, "taxi passenger surcharge from TD taxi fare table", fare_url),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "tunnel_id",
            "tunnel_name",
            "taxi_type",
            "taxi_passenger_surcharge_hkd",
            "rule_note",
            "source_url",
        ],
    )
    frame["private_vehicle_road_toll_hkd"] = pd.NA
    frame["private_vehicle_toll_note"] = (
        "Private vehicle tolls are maintained separately and are not used as taxi passenger surcharge."
    )
    frame["fare_effective_date"] = "2024-07-14"
    frame.loc[frame["tunnel_id"].eq("tai_lam_tunnel"), "fare_effective_date"] = "2025-05-31"
    frame["source_file"] = frame["source_url"].map(
        {url: file_name for file_name, url in SOURCE_URLS.items()}
    ).fillna("td_taxi_fare_of_hong_kong.html")
    frame["source_download_date"] = download_date
    frame["currency"] = "HKD"
    return frame


def type_assignment_md() -> str:
    return """# Hong Kong taxi type assignment rules v1

This file records the conservative offline assignment used by
`estimate_hong_kong_taxi_leg_fares.py`. It is not written back to MATSim plans.

Official source:
Transport Department, "Details of taxi operating areas".

Rules:

1. If the candidate tour contains unresolved TCS zones (`-1`) or unresolved
   facility-area evidence, assign `unresolved`.
2. If all known tour zones are in the North Lantau set `{22}`, assign
   `lantau_taxi`.
3. If all known tour zones are in the New Territories set
   `{14,15,16,17,18,19,20,21,23,24,25}`, assign
   `new_territories_taxi`.
4. If the tour uses urban/Hong Kong Island/Kowloon/Tsuen Wan/Kwai Chung/Tsing
   Yi zones `{1,2,3,4,5,6,7,8,9,10,11,12,13}` or crosses urban and ordinary
   New Territories zones, assign `urban_taxi`, because urban taxis are the
   general Hong Kong taxi type except for restricted Lantau roads.
5. If a tour mixes Lantau evidence with non-Lantau zones, assign `unresolved`
   and calculate fare ranges under all three taxi fare tables.

The rule deliberately avoids allocating taxi type by fleet proportion alone.
Unresolved tours remain explicit in the fare outputs.
"""


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sources = download_sources(args.raw_dir, args.force_download)

    fare = fare_rules(DOWNLOAD_DATE)
    tunnel = tunnel_rules(DOWNLOAD_DATE)
    fare.to_csv(args.out_dir / "taxi_fare_rules.csv", index=False, encoding="utf-8-sig")
    tunnel.to_csv(args.out_dir / "taxi_tunnel_surcharge_rules.csv", index=False, encoding="utf-8-sig")
    (args.out_dir / "taxi_type_assignment_rules.md").write_text(type_assignment_md(), encoding="utf-8")

    manifest = {
        "created_date": DOWNLOAD_DATE,
        "currency": "HKD",
        "source_files": sources,
        "outputs": {
            "taxi_fare_rules.csv": "Machine-readable taxi meter fare rules.",
            "taxi_tunnel_surcharge_rules.csv": "Taxi passenger tunnel surcharge rules, separate from private-vehicle tolls.",
            "taxi_type_assignment_rules.md": "Conservative offline taxi-type assignment rules.",
        },
    }
    (args.out_dir / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"out_dir": args.out_dir.as_posix(), "source_files": len(sources)}, indent=2))


if __name__ == "__main__":
    main()
